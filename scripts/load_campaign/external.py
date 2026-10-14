#!/usr/bin/env python3
"""Small real-internet accounting check from the operator Mac; no artificial impairment."""
import datetime
import hashlib
import json
import os
import pathlib
import re
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
    clock = subprocess.run(['sntp', '-t', '5', 'time.apple.com'], capture_output=True, text=True, timeout=45)
    (local / 'operator-clock.txt').write_text(clock.stdout + clock.stderr)
    clock_samples = re.findall(r'([+-]\d+\.\d+) \+/- (\d+\.\d+)', clock.stdout)
    if not clock_samples:
        raise RuntimeError('No fresh external clock sample; preserve attempt before retrying')
    offset, uncertainty = map(float, clock_samples[-1])
    game_directory = run.REMOTE + "/" + name + "/game"
    unit = run.UNIT_PREFIX + name
    config = run.configure("instrumented", "native")
    run.ssh("game", "rm -f /var/lib/omega-measure/current/window.json; sudo -n systemctl restart omega-loadtest-arena.service")
    run.ssh("game", f"mkdir -p {game_directory}")
    peer = run.ACCESS['operator_ipv4_cidr'].split('/')[0]
    nft = 'table inet omega_measure { chain input { type filter hook input priority -150; policy accept; ip saddr ' + peer + ' udp dport 8081 counter comment "bot_in"; }; chain output { type filter hook output priority -150; policy accept; ip daddr ' + peer + ' udp sport 8081 counter comment "game_out"; }; }'
    run.ssh("game", "sudo -n nft delete table inet omega_measure 2>/dev/null || true")
    run.ssh("game", "printf '%s' " + shlex.quote(nft) + " | sudo -n nft -f -")
    command = f"python3 {run.REMOTE}/host_collect.py --role game --directory {game_directory} --seconds 600"
    run.ssh("game", f"sudo -n systemd-run --quiet --unit={unit}-game-collect --uid=deploy /bin/bash -c " + shlex.quote(command))
    command = f"exec python3 {run.REMOTE}/capture.py {game_directory} eth0 {peer}" + (" --article" if run.ARTICLE_POINTS else "")
    run.ssh("game", f"sudo -n systemd-run --quiet --property=KillMode=mixed --unit={unit}-game-capture /bin/bash -c " + shlex.quote(command))
    binary = run.ROOT / "rust/target/release/omega-load-test"
    args = [str(binary), "--server", run.HOSTS["game"]["ipv4"] + ":8081", "--bots", "3", "--behavior", "combat",
            "--duration", "360", "--input-hz", "30", "--seed", "30", "--stagger", "100", "--difficulty", "1.0",
            "--bandwidth-budget", "0", "--assertions", "strict", "--aoi-exit-radius", "1100", "--output", str(bots_directory / "bot.json")]
    socket_path = bots_directory / ("socket-stream.pipe" if run.ARTICLE_POINTS else "socket-payloads.pcap")
    flow_process = None
    flow_log = None
    if run.ARTICLE_POINTS:
        os.mkfifo(socket_path, 0o600)
        flow_log = (bots_directory / 'capture.log').open('x')
        command = shlex.join([str(run.RAW / 'flow-record-macos'), str(bots_directory), '--article']) + ' < ' + shlex.quote(str(socket_path))
        flow_process = subprocess.Popen(['/bin/sh', '-c', 'exec ' + command], stderr=flow_log)
    environment = dict(os.environ)
    for key in ("OMEGA_TICKET_API", "OMEGA_LOAD_TEST_SECRET"):
        environment.pop(key, None)
    environment.update(OMEGA_MEASURE_DIR=str(bots_directory), OMEGA_SOCKET_PCAP=str(socket_path),
                       DYLD_INSERT_LIBRARIES=str(run.RAW / "socket-capture.dylib"))
    manifest = {"run_id": name, "requested_bots": 3, "behavior": "combat", "duration": 360, "excluded_warmup": 60,
                "profile": "native", "variant": "native", "repeat": 1, "build": "instrumented",
                "topology": "Operator Mac/Taiwan internet to Falkenstein game CAX11; bot VPS not generating load",
                "collection": True, "collection_format": "article-points-v1" if run.ARTICLE_POINTS else "legacy-full", "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "game_config": config, "command": shlex.join(args), "input_hz": 30, "seed": 30, "stagger_ms": 100,
                "difficulty": 1.0, "bandwidth_budget": 0,
                "local_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "local_socket_observer_sha256": hashlib.sha256((run.RAW / "socket-capture.dylib").read_bytes()).hexdigest(),
                "external_clock_evidence": f"operator-clock.txt; sntp offset {offset * 1000:+.3f} ms with ±{uncertainty * 1000:.3f} ms uncertainty",
                "external_clock_offset_ms": offset * 1000,
                "external_clock_uncertainty_ms": uncertainty * 1000,
                "external_socket_capture_semantics": "Successful UDP payloads at send completion and socket receive observation; synthetic 20-byte IPv4 +8-byte UDP headers, no link/NIC counters. Game-host IP counters/capture are authoritative for outbound transfer.",
                "provider_reconciliation": "Earlier game-host tooltip is retained in game-provider-counter-before.json; seek a fresh before/after reading and account for provider delay and unrelated egress."}
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (local / "game-run-provenance.txt").write_text(run.ssh("game",
        f"sha256sum {run.MEASURED_BY_ROLE['game']}/omega-server /etc/omega-loadtest/arena.json {run.REMOTE}/host_collect.py {run.REMOTE}/capture.py {run.REMOTE}/flow-record; "
        f"git -C {shlex.quote(run.MEASURED_CHECKOUTS['game'])} rev-parse HEAD; git -C {shlex.quote(run.MEASURED_CHECKOUTS['game'])} status --short; "
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
                    (bots_directory / 'window.json').write_text(json.dumps(window))
                    run.copy("game", local / "window.json", game_directory + "/window.json.partial")
                    run.ssh("game", f"mv {game_directory}/window.json.partial {game_directory}/window.json")
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
        flow_error = None
        if flow_process is not None:
            if process is None:
                flow_process.terminate()
            try:
                result = flow_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                flow_process.kill()
                result = flow_process.wait()
                flow_error = 'External recorder did not drain within 30 seconds'
            flow_log.close()
            socket_path.unlink()
            if result:
                flow_error = flow_error or 'External streaming recorder failed'
                (local / 'collection-error.txt').write_text(flow_error)
        run.ssh('game', f"cp /var/lib/omega-measure/current/ticks.csv /var/lib/omega-measure/current/server.ndjson {game_directory}/; sudo -n chown -R deploy:deploy {game_directory}")
        if run.ARTICLE_POINTS:
            import article_points
            article_points.curate(bots_directory)
            run.ssh('game', f"python3 {run.REMOTE}/article_points.py {game_directory}")
        run.ssh("game", f"sudo -n chown -R deploy:deploy {game_directory}; tar -czf {run.REMOTE}/{name}-game.tar.gz -C {run.REMOTE}/{name} game")
        run.copy("game", run.REMOTE + "/" + name + "-game.tar.gz", local / "game.tar.gz", download=True)
        run.ssh("game", "sudo -n nft delete table inet omega_measure")
    if not run.ARTICLE_POINTS:
        with socket_path.open("rb") as stream, (bots_directory / "capture.log").open("w") as log:
            subprocess.run([str(run.RAW / "flow-record-macos"), str(bots_directory)], stdin=stream, stderr=log, check=True)
    with tarfile.open(local / "bots.tar.gz", "w:gz") as archive:
        archive.add(bots_directory, arcname="bots")
    if flow_error:
        raise RuntimeError(flow_error)
    manifest["ended_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(name + ": evidence retained", flush=True)


if __name__ == "__main__":
    main()
