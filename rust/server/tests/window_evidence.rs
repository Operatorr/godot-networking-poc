//! The server's common-window recorders, through the real binary: create-only files, and a count
//! that exposes truncation. Without the opt-in, a reused directory keeps today's behavior.
#![cfg(unix)]

use std::net::UdpSocket;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct Server(Child);

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn directory(label: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "omega-window-evidence-{label}-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&path).unwrap();
    path
}

fn free_port() -> u16 {
    UdpSocket::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

fn start(measure_dir: &Path, window_evidence: bool) -> Server {
    let mut command = Command::new(env!("CARGO_BIN_EXE_omega-server"));
    command
        .args([
            "--mode",
            "arena",
            "--port",
            &free_port().to_string(),
            "--allow-unsigned-tickets",
        ])
        .env("OMEGA_MEASURE_DIR", measure_dir)
        .env("OMEGA_METRICS_PORT", "0")
        .current_dir(measure_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if window_evidence {
        command.env("OMEGA_MEASURE_WINDOW_EVIDENCE", "1");
    }
    Server(command.spawn().unwrap())
}

fn wait_for(path: &Path, limit: Duration) -> bool {
    let deadline = Instant::now() + limit;
    while Instant::now() < deadline {
        if path.exists() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    false
}

fn interrupt(server: &mut Server) {
    Command::new("kill")
        .args(["-INT", &server.0.id().to_string()])
        .status()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if server.0.try_wait().unwrap().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("the server did not stop on SIGINT");
}

#[test]
fn window_evidence_finishes_with_a_count_of_what_it_wrote() {
    let dir = directory("final");
    let mut server = start(&dir, true);
    assert!(wait_for(&dir.join("process.json"), Duration::from_secs(10)));
    std::thread::sleep(Duration::from_millis(1500));
    interrupt(&mut server);
    let process: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("process.json")).unwrap()).unwrap();
    assert_eq!(process["pid"], server.0.id());
    assert_eq!(process["role"], "game");
    assert!(process["clock"]["mono_ns"].is_u64());
    let last: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("final.json")).unwrap()).unwrap();
    let ticks = std::fs::read_to_string(dir.join("ticks.csv")).unwrap();
    assert_eq!(last["tick_rows"], ticks.lines().count() as u64 - 1);
    assert!(last["tick_rows"].as_u64().unwrap() > 0);
    let population = std::fs::read_to_string(dir.join("population.ndjson")).unwrap();
    let rows: Vec<serde_json::Value> = population
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(last["population_rows"], rows.len() as u64);
    for (index, row) in rows.iter().enumerate() {
        assert_eq!(row["seq"], index as u64);
    }
    assert_eq!(rows.last().unwrap()["k"], "footer");
    assert!(rows.iter().any(|row| row["k"] == "clock"));
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn window_evidence_never_replaces_earlier_bytes() {
    let dir = directory("create-only");
    std::fs::write(dir.join("ticks.csv"), "kept").unwrap();
    let mut server = start(&dir, true);
    let status = server.0.wait().unwrap();
    assert!(
        !status.success(),
        "the server must refuse rather than overwrite"
    );
    assert_eq!(
        std::fs::read_to_string(dir.join("ticks.csv")).unwrap(),
        "kept"
    );
    std::fs::remove_dir_all(dir).unwrap();
}

#[test]
fn historical_measurement_directories_still_restart_in_place() {
    let dir = directory("legacy");
    std::fs::write(dir.join("ticks.csv"), "replaced").unwrap();
    let mut server = start(&dir, false);
    let deadline = Instant::now() + Duration::from_secs(10);
    while std::fs::read_to_string(dir.join("ticks.csv")).unwrap() == "replaced" {
        assert!(
            Instant::now() < deadline,
            "the legacy recorder never started"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    interrupt(&mut server);
    assert!(!dir.join("population.ndjson").exists());
    assert!(!dir.join("final.json").exists());
    std::fs::remove_dir_all(dir).unwrap();
}
