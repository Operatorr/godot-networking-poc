#!/usr/bin/env python3
"""Small real-internet accounting check from the operator Mac; no artificial impairment."""
import datetime
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import tarfile
import time
import run


def main():
    name = "external-combat-3-r1"
    local = run.RAW / name
    if local.exists():
        raise RuntimeError("Refusing to overwrite external evidence")
    local.mkdir()
    bots_directory = local / "bots"
    bots_directory.mkdir()
    game_directory = run.REMOTE + "/" + name + "/game"
    unit = "omega-campaign-" + name
    config = run.configure("instrumented", "native")
    run.ssh("game", "rm -f /var/lib/omega-measure/current/window.json; sudo -n systemctl restart omega-loadtest-arena.service")
    run.ssh("game", f"mkdir -p {game_directory}")
    nft = 'table inet omega_measure { chain input { type filter hook input priority -150; policy accept; udp dport 8081 counter comment "bot_in"; }; chain output { type filter hook output priority -150; policy accept; udp sport 8081 counter comment "game_out"; }; }'
    run.ssh("game", "sudo -n nft delete table inet omega_measure 2>/dev/null || true")
    run.ssh("game", "printf '%s' " + shlex.quote(nft) + " | sudo -n nft -f -")
    command = f"python3 {run.REMOTE}/host_collect.py --role game --directory {game_directory} --seconds 600"
    run.ssh("game", f"sudo -n systemd-run --quiet --unit={unit}-game-collect --uid=deploy /bin/bash -c " + shlex.quote(command))
    command = f"exec python3 {run.REMOTE}/capture.py {game_directory}"
    run.ssh("game", f"sudo -n systemd-run --quiet --property=KillMode=mixed --unit={unit}-game-capture /bin/bash -c " + shlex.quote(command))
    binary = run.ROOT / "rust/target/release/omega-load-test"
    args = [str(binary), "--server", run.HOSTS["game"]["ipv4"] + ":8081", "--bots", "3", "--behavior", "combat",
            "--duration", "360", "--input-hz", "30", "--seed", "30", "--stagger", "100", "--difficulty", "1.0",
            "--bandwidth-budget", "0", "--assertions", "strict", "--aoi-exit-radius", "1100", "--output", str(bots_directory / "bot.json")]
    environment = dict(os.environ)
    for key in ("OMEGA_TICKET_API", "OMEGA_LOAD_TEST_SECRET"):
        environment.pop(key, None)
    environment.update(OMEGA_MEASURE_DIR=str(bots_directory), OMEGA_SOCKET_PCAP=str(bots_directory / "socket-payloads.pcap"),
                       DYLD_INSERT_LIBRARIES=str(run.RAW / "socket-capture.dylib"))
    manifest = {"run_id": name, "requested_bots": 3, "behavior": "combat", "duration": 360, "excluded_warmup": 60,
                "profile": "native", "variant": "native", "repeat": 1, "build": "instrumented",
                "topology": "Operator Mac/Taiwan internet to Falkenstein game CAX11; bot VPS not generating load",
                "collection": True, "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "game_config": config, "command": shlex.join(args), "input_hz": 30, "seed": 30, "stagger_ms": 100,
                "difficulty": 1.0, "bandwidth_budget": 0,
                "local_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "local_socket_observer_sha256": hashlib.sha256((run.RAW / "socket-capture.dylib").read_bytes()).hexdigest(),
                "external_clock_evidence": "operator-clock.txt; sntp offset +0.282 ms with ±35.746 ms uncertainty",
                "external_socket_capture_semantics": "Successful UDP payloads at send completion and socket receive observation; synthetic 20-byte IPv4 +8-byte UDP headers, no link/NIC counters. Game-host IP counters/capture are authoritative for outbound transfer.",
                "provider_reconciliation": "Earlier game-host tooltip is retained in game-provider-counter-before.json; seek a fresh before/after reading and account for provider delay and unrelated egress."}
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (local / "game-run-provenance.txt").write_text(run.ssh("game",
        f"sha256sum {run.MEASURED}/omega-server /etc/omega-loadtest/arena.json {run.REMOTE}/host_collect.py {run.REMOTE}/capture.py {run.REMOTE}/flow-record; "
        "git -C /home/deploy/omega-measured rev-parse HEAD; git -C /home/deploy/omega-measured status --short; "
        "systemctl cat omega-loadtest-arena.service; chronyc tracking; tc -s -j qdisc show dev eth0"))
    (local / "bots-run-provenance.txt").write_text("Operator macOS external generator. Binary and observer SHA-256 in manifest. "
        "Socket observations are not NIC timestamps. Local code hash matches separately retained build evidence.\n")
    process = None
    try:
        with (bots_directory / "bot.log").open("w") as log:
            process = subprocess.Popen(args, env=environment, stdout=log, stderr=subprocess.STDOUT)
            print(name + ": local external swarm started", flush=True)
            window_written = False
            deadline = time.monotonic() + 450
            while process.poll() is None and time.monotonic() < deadline:
                observation = {"utc_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns(),
                               "process_ps": subprocess.run(["ps", "-p", str(process.pid), "-o", "pid=,time=,rss=,%cpu="], capture_output=True, text=True).stdout}
                with (bots_directory / "operator-host.ndjson").open("a") as output:
                    output.write(json.dumps(observation) + "\n")
                if not window_written and (bots_directory / "phase.json").exists():
                    phase = json.loads((bots_directory / "phase.json").read_text())["phase2_utc_ns"]
                    window = {"start": phase + 60_000_000_000, "end": phase + 360_000_000_000}
                    (local / "window.json").write_text(json.dumps(window))
                    run.copy("game", local / "window.json", game_directory + "/window.json")
                    run.ssh("game", f"cp {game_directory}/window.json /var/lib/omega-measure/current/window.json")
                    window_written = True
                    print(name + ": five-minute window scheduled", flush=True)
                time.sleep(1)
            if process.poll() is None:
                process.terminate()
                raise RuntimeError("External swarm timeout")
            (bots_directory / "exit-code").write_text(str(process.returncode))
    finally:
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=10)
        run.ssh("game", f"sudo -n systemctl stop {unit}-game-collect {unit}-game-capture")
        run.ssh("game", f"cp /var/lib/omega-measure/current/ticks.csv /var/lib/omega-measure/current/server.ndjson {game_directory}/; sudo -n chown -R deploy:deploy {game_directory}; tar -czf {run.REMOTE}/{name}-game.tar.gz -C {run.REMOTE}/{name} game")
        run.copy("game", run.REMOTE + "/" + name + "-game.tar.gz", local / "game.tar.gz", download=True)
        run.ssh("game", "sudo -n nft delete table inet omega_measure")
    with (bots_directory / "socket-payloads.pcap").open("rb") as stream, (bots_directory / "capture.log").open("w") as log:
        subprocess.run([str(run.RAW / "flow-record-macos"), str(bots_directory)], stdin=stream, stderr=log, check=True)
    with tarfile.open(local / "bots.tar.gz", "w:gz") as archive:
        archive.add(bots_directory, arcname="bots")
    manifest["ended_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(name + ": evidence retained", flush=True)


if __name__ == "__main__":
    main()
