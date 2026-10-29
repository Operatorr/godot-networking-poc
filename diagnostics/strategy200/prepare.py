#!/usr/bin/env python3
"""Materialize a pinned diagnostic workspace; never modify the production workspace."""
import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
REV = "a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf"
OUT = HERE / ".prepared"


def replace(s, old, new):
    assert s.count(old) == 1, (old[:100], s.count(old))
    return s.replace(old, new)


def main():
    if OUT.exists():
        raise SystemExit("Refusing to overwrite an existing prepared experiment")
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", REV, "rust", "scripts/load_campaign"], cwd=ROOT, text=True
    ).splitlines()
    hashes = {}
    for p in paths:
        if not (p in ("rust/Cargo.toml", "rust/Cargo.lock") or p.startswith("scripts/load_campaign/udp_control_") and p.endswith(".rs") or
                any(p.startswith("rust/" + c + "/") for c in ("protocol", "sim_core", "load_test"))):
            continue
        data = subprocess.check_output(["git", "show", REV + ":" + p], cwd=ROOT)
        target = OUT / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[p] = hashlib.sha256(data).hexdigest()
    workspace = OUT / "rust/Cargo.toml"
    workspace.write_text(replace(workspace.read_text(),
        'members = ["protocol", "sim_core", "server", "client_ext", "load_test"]',
        'members = ["protocol", "sim_core", "load_test"]'))
    source = OUT / "rust/load_test/src"
    original = (source / "bot.rs").read_text()
    # Identical constructor-only seam in both references: inject the public ENet
    # Socket/time interfaces. Real socket initialization remains byte-for-byte.
    baseline = replace(original, "pub struct Bot {", "pub struct Bot<S: enet::Socket<Address = SocketAddr> = UdpSocket> {")
    baseline = replace(baseline, "host: enet::Host<crate::native_diagnostic::ObservedSocket>,",
                       "host: enet::Host<crate::native_diagnostic::ObservedSocket<S>>,")
    baseline = replace(baseline, "let mut host = enet::Host::new(", "let host = enet::Host::new(")
    marker = "        let peer_key = host\n"
    baseline = replace(baseline, marker,
        "        Self::from_host(host, id, server, behavior, difficulty, input_hz, bandwidth_budget_bps, seed, ticket, now)\n"
        "    }\n}\n\n"
        "impl<S: enet::Socket<Address = SocketAddr>> Bot<S> {\n"
        "    #[allow(clippy::too_many_arguments)]\n"
        "    pub fn from_host(mut host: enet::Host<crate::native_diagnostic::ObservedSocket<S>>, id: u32, server: SocketAddr, behavior: BehaviorKind, difficulty: f64, input_hz: f64, bandwidth_budget_bps: u32, seed: Option<u64>, ticket: Option<Ticket>, now: f64) -> std::io::Result<Self> {\n"
        + marker)
    # Harness-only witnesses observe the real application handling and encoded
    # sends. They are compiled out of the remote executable.
    baseline = replace(baseline, "    pub id: u32,", "    #[cfg(feature = \"synthetic-replay\")]\n    pub replay_trace: Option<Vec<(u64, u8, Vec<u8>)>>,\n    pub id: u32,")
    baseline = replace(baseline, "            id,\n            phase:", "            #[cfg(feature = \"synthetic-replay\")]\n            replay_trace: None,\n            id,\n            phase:")
    baseline = replace(baseline, "            match event {", """            #[cfg(feature = "synthetic-replay")]
            if let Some(trace) = &mut self.replay_trace {
                let (kind, bytes) = match &event {
                    enet::EventNoRef::Receive { packet, channel_id, .. } => (*channel_id, packet.data().to_vec()),
                    enet::EventNoRef::Connect { .. } => (250, vec![]),
                    enet::EventNoRef::Disconnect { data, .. } => (251, data.to_le_bytes().to_vec()),
                };
                trace.push(((now * 1000.0).round() as u64, kind, bytes));
            }
            match event {""")
    baseline = replace(baseline, "        let bytes = packet.encode();", """        let bytes = packet.encode();
        #[cfg(feature = "synthetic-replay")]
        if let Some(trace) = &mut self.replay_trace {
            trace.push((self.host.now().as_millis() as u64, 252, bytes.clone()));
        }""")
    (source / "bot_reference.rs").write_text(baseline)
    candidate = replace(baseline, "    pub id: u32,", "    pub event_budget: usize,\n    pub id: u32,")
    candidate = replace(candidate, "            id,\n            phase:", "            event_budget: crate::sweep::event_budget(),\n            id,\n            phase:")
    candidate = replace(candidate, "    fn drain_events(&mut self, now: f64) {\n        loop {", """    fn drain_events(&mut self, now: f64) {
        let mut delivered = 0;
        loop {
            if self.event_budget != 0 && delivered == self.event_budget {
                return;
            }""")
    candidate = replace(candidate, '            match event {', '            delivered += 1;\n            match event {')
    (source / "bot.rs").write_text(candidate)
    main_rs = (source / "main.rs").read_text()
    main_rs = replace(main_rs, "mod ticket;", "mod ticket;\nmod sweep;")
    main_rs = replace(main_rs, "fn main() {", "fn main() {\n    sweep::validate();")
    main_rs = replace(main_rs, "fn poll_all(bots: &mut [Bot], now: f64) {", "fn poll_all(bots: &mut [Bot], now: f64) {\n    let sweep_started = sweep::global_start();")
    main_rs = replace(main_rs, "\n}\n\n/// Best-effort extraction", "\n    sweep::global_finish(sweep_started, bots.len());\n}\n\n/// Best-effort extraction")
    (source / "main.rs").write_text(main_rs)
    measure = (source / "measurement.rs").read_text()
    for method in ("sample", "sample_ramp", "sample_phase"):
        measure = replace(measure, "fn " + method + "(", "fn " + method + "<S: rusty_enet::Socket<Address = std::net::SocketAddr>>(")
    measure = measure.replace("crate::bot::Bot]", "crate::bot::Bot<S>]")
    measure = replace(measure, '"gap_bounds_ms": GAP_BOUNDS_MS, "bots": observations',
                      '"gap_bounds_ms": GAP_BOUNDS_MS, "bots": observations, "sweep": crate::sweep::global_snapshot()')
    (source / "measurement.rs").write_text(measure)
    (source / "sweep.rs").write_bytes((HERE / "src/sweep.rs").read_bytes())
    bins = source / "bin"
    bins.mkdir()
    (bins / "poll-replay.rs").write_bytes((HERE / "src/replay.rs").read_bytes())
    cargo = OUT / "rust/load_test/Cargo.toml"
    cargo.write_text(cargo.read_text() + '\n[features]\nsynthetic-replay = []\n\n[[bin]]\nname = "poll-replay"\npath = "src/bin/poll-replay.rs"\nrequired-features = ["synthetic-replay"]\n')
    subprocess.run(["cargo", "fmt", "--all"], cwd=OUT / "rust", check=True)
    for filename, content in (("candidate-vs-original.diff", original), ("candidate-vs-reference.diff", (source / "bot_reference.rs").read_text())):
        before = OUT / (filename + ".before")
        before.write_text(content)
        diff = subprocess.run(["diff", "-u", str(before), str(source / "bot.rs")], capture_output=True)
        (OUT / filename).write_bytes(diff.stdout)
    (OUT / "provenance.json").write_text(json.dumps({"revision": REV, "original_sha256": hashes}, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
