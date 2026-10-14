#!/usr/bin/env python3
"""Reclaim only unpacked duplicates after verified archives exist locally and on the host.

Never removes an archive or a live run. Waits for a gap with no bot swarm so disk cleanup
does not overlap scored generation. Original binary/config provenance is outside this scope.
"""
import json
import pathlib
import shlex
import time
import run

ledger_path = run.RAW / "unpacked-duplicate-cleanup.json"
ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
while True:
    completed = []
    for path in run.RAW.glob("*/manifest.json"):
        name = path.parent.name
        if not name.startswith(("core-", "boundary-", "idle-", "network-", "transfer-")) or name in ledger:
            continue
        manifest = json.loads(path.read_text())
        if manifest.get("ended_utc") and all((path.parent / (role + ".tar.gz")).exists() for role in run.HOSTS):
            completed.append(path.parent)
    if completed:
        busy = run.ssh("bots", "if pgrep -x omega-load-test >/dev/null; then echo BUSY; else echo IDLE; fi").strip()
        if busy == "IDLE":
            for directory in completed:
                if run.ssh("bots", "if pgrep -x omega-load-test >/dev/null; then echo BUSY; else echo IDLE; fi").strip() != "IDLE":
                    break
                sizes = {role: (directory / (role + ".tar.gz")).stat().st_size for role in run.HOSTS}
                removed = []
                for role, size in sizes.items():
                    archive = run.REMOTE + "/" + directory.name + "-" + role + ".tar.gz"
                    remote_size = run.ssh(role, "stat -c %s " + shlex.quote(archive)).strip()
                    if remote_size != str(size):
                        raise RuntimeError("Archive size differs; preserving unpacked evidence")
                    target = run.REMOTE + "/" + directory.name + "/" + role
                    command = "import shutil; shutil.rmtree(" + repr(target) + ", ignore_errors=True)"
                    run.ssh(role, "python3 -c " + shlex.quote(command))
                    removed.append(role)
                ledger[directory.name] = {"removed_only_unpacked_duplicates": removed,
                                          "retained_local_archives": str(directory.relative_to(run.ROOT)),
                                          "retained_remote_archives": [run.REMOTE + "/" + directory.name + "-" + role + ".tar.gz" for role in run.HOSTS],
                                          "transport": "Controller copy verifies remote/local SHA-256 before completed manifest; archive sizes rechecked here"}
                ledger_path.write_text(json.dumps(ledger, indent=2))
                print("Reclaimed unpacked duplicates:", directory.name, flush=True)
    time.sleep(10)
