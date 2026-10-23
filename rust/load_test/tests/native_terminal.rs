//! Real CLI/ENet lifecycle: retain the native suffix after queued input teardown.
use rusty_enet::{EventNoRef, Host, HostSettings, Packet};
use std::{
    net::UdpSocket,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

#[test]
fn cli_records_native_counters_after_disconnect_and_force_close() {
    let directory =
        std::env::temp_dir().join(format!("omega-native-terminal-{}", std::process::id()));
    std::fs::create_dir(&directory).unwrap();
    let socket = UdpSocket::bind("127.0.0.1:0").unwrap();
    let address = socket.local_addr().unwrap();
    let mut host = Host::new(
        socket,
        HostSettings {
            peer_limit: 1,
            channel_limit: 3,
            ..Default::default()
        },
    )
    .unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_omega-load-test"))
        .args([
            "--server",
            &address.to_string(),
            "--bots",
            "1",
            "--duration",
            "1",
            "--stagger",
            "0",
            "--behavior",
            "idle",
            "--no-report",
        ])
        .env("OMEGA_MEASURE_DIR", &directory)
        .env("OMEGA_NATIVE_DIAG", "v1")
        .env_remove("OMEGA_TICKET_API")
        .env_remove("OMEGA_LOAD_TEST_SECRET")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(8);
    let mut inputs = 0;
    loop {
        while let Some(event) = host.service().unwrap().map(|e| e.no_ref()) {
            if let EventNoRef::Receive { peer, packet, .. } = event {
                match protocol::ClientPacket::decode(packet.data()).unwrap() {
                    protocol::ClientPacket::ConnectAuth(_) => {
                        let auth = protocol::ServerPacket::AuthResult(protocol::AuthResult {
                            result: protocol::types::auth_result_code::OK,
                            ok: Some(protocol::AuthOk {
                                entity_id: 1,
                                server_tick: 0,
                                tick_rate: 30,
                            }),
                        });
                        host.peer_mut(peer)
                            .send(1, &Packet::reliable(auth.encode()))
                            .unwrap();
                    }
                    protocol::ClientPacket::PlayerInput(_) => inputs += 1,
                    _ => {}
                }
            }
        }
        if child.try_wait().unwrap().is_some() {
            break;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("CLI did not terminate");
        }
        std::thread::sleep(Duration::from_millis(1));
    }
    let rows: Vec<serde_json::Value> = std::fs::read_to_string(directory.join("bots.ndjson"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let final_row = rows.last().unwrap();
    assert!(inputs > 0, "exercise actual authenticated input traffic");
    assert!(
        rows.iter().any(|r| r["boundary"] == "end"),
        "retain measurement endpoint"
    );
    assert_eq!(
        final_row["boundary"], "drained",
        "missing post-teardown counter snapshot"
    );
    assert_eq!(final_row["bots"][0]["phase"], "Closed");
    let native = &final_row["bots"][0]["native_diagnostic"];
    assert_eq!(native["pending_inputs"], 0);
    assert_eq!(native["counts"]["admitted"], native["counts"]["retired"]);
    assert_eq!(
        std::fs::metadata(directory.join("native-1.bin"))
            .unwrap()
            .len(),
        native["trace_bytes"].as_u64().unwrap()
    );
    std::fs::remove_dir_all(directory).unwrap();
}
