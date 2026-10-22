//! Exercise the real join loop: a peer that never answers must still produce evidence.
#![cfg(unix)]

use std::net::UdpSocket;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct Swarm(Child);

impl Drop for Swarm {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn unsettled_join_records_ramp_before_phase_two() {
    // Keep a real UDP endpoint open but never answer its ENet handshake.
    let blackhole = UdpSocket::bind("127.0.0.1:0").unwrap();
    let directory = std::env::temp_dir().join(format!(
        "omega-ramp-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&directory).unwrap();
    let mut swarm = Swarm(
        Command::new(env!("CARGO_BIN_EXE_omega-load-test"))
            .args([
                "--server",
                &blackhole.local_addr().unwrap().to_string(),
                "--bots",
                "1",
                "--duration",
                "1",
                "--behavior",
                "idle",
            ])
            .env("OMEGA_MEASURE_DIR", &directory)
            .env_remove("OMEGA_TICKET_API")
            .env_remove("OMEGA_LOAD_TEST_SECRET")
            .current_dir(&directory)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(3);
    let mut observations = Vec::new();
    while Instant::now() < deadline {
        observations = std::fs::read_to_string(directory.join("bots.ndjson"))
            .unwrap_or_default()
            .lines()
            .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
            .collect();
        if observations.len() >= 2 {
            break;
        }
        assert!(
            swarm.0.try_wait().unwrap().is_none(),
            "swarm exited during join"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    let phase_two_started = directory.join("phase.json").exists();
    drop(swarm);
    std::fs::remove_dir_all(directory).unwrap();
    assert!(!phase_two_started, "test must exercise an unfinished join");
    assert!(
        observations.len() >= 2,
        "missing periodic observations during an unsettled join"
    );
    for row in &observations {
        assert_eq!(row["phase"], "ramp");
        assert!(
            row["phase_s"].is_null(),
            "ramp is outside the steady-phase clock"
        );
        assert_eq!(row["bots"].as_array().unwrap().len(), 1);
        assert_eq!(row["bots"][0]["phase"], "Connecting");
        assert_eq!(row["bots"][0]["inputs"], 0);
    }
    assert!(observations[1]["utc_ns"].as_u64() > observations[0]["utc_ns"].as_u64());
}
