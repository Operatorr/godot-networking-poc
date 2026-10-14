#!/usr/bin/env python3
"""Publish redacted observations and derived results; retain packet archives privately."""
import gzip
import hashlib
import json
import pathlib
import tarfile
import sys
import run

OUTPUT = run.ROOT / "docs/netcode/perf-notes/load-test-reports/2026-10-13"


def redact(text):
    for host in run.HOSTS.values():
        text = text.replace(host["ipv4"], "<" + host["role"] + "-host>")
    return text.replace(run.ACCESS["operator_ipv4_cidr"].split("/")[0], "<operator-host>")


def publish(run_id):
    source = run.RAW / run_id
    target = OUTPUT / run_id
    target.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "steady.json", "window.json", "controller-error.txt", "ramp-failure.json", "analysis-error.txt", "foreign-flow-forensics.json", "peer-filter-validation.json", "capture-peer-inventory.json", "boot.log",
                 "game-run-provenance.txt", "bots-run-provenance.txt", "game-final-service.txt", "bots-final-service.txt"):
        if (source / name).exists():
            (target / name).write_text(redact((source / name).read_text()))
    checksums = {}
    for archive_path in source.glob("*.tar.gz"):
        with archive_path.open('rb') as evidence:
            checksums[archive_path.name] = hashlib.file_digest(evidence, 'sha256').hexdigest()
        role = archive_path.stem.split(".")[0]
        with tarfile.open(archive_path) as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.name.endswith((".pcap", ".bin")):
                    continue
                content = archive.extractfile(member).read()
                if member.name.endswith(".gz"):
                    content = gzip.decompress(content)
                text = redact(content.decode())
                if member.name.endswith(("/start.json", "/end.json")):
                    row = json.loads(text)
                    row.pop("net/udp", None)
                    row.pop("net/udp6", None)
                    text = json.dumps(row, indent=2)
                # Host proc/socket observations retain local addresses and contain thousands
                # of redundant status fields. Publish the timestamped metrics exposition and
                # interface/process/CPU/flow observations after removing network endpoint data.
                if member.name.endswith("host.ndjson.gz"):
                    observations = []
                    for line in text.splitlines():
                        row = json.loads(line)
                        row.pop("net/udp", None)
                        row.pop("net/udp6", None)
                        observations.append(json.dumps(row))
                    text = "\n".join(observations) + "\n"
                destination = target / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if member.name.endswith((".ndjson", ".csv", "host.ndjson.gz")):
                    if not destination.name.endswith(".gz"):
                        destination = destination.with_name(destination.name + ".gz")
                    with destination.open("wb") as buffer, gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as output:
                        output.write(text.encode())
                else:
                    destination.write_text(text)
    compact = json.loads((source / "manifest.json").read_text()).get("collection_format") == "article-points-v1"
    (target / "retained-evidence.json").write_text(json.dumps({
        "original_archives_relative_location": str(source.relative_to(run.ROOT)),
        "sha256": checksums,
        "contents": "Curated article graph points, exact counters and bounded diagnostics; only 1/64 fingerprint samples privately retained, no raw packet archive." if compact else "Unedited reports/logs, host observations, packet headers and full-datagram ENet descriptors. Retained off both temporary hosts in the ignored local evidence archive. Public copies redact connection addresses; no access records or credentials are published.",
    }, indent=2))


if __name__ == "__main__":
    for run_id in sys.argv[1:]:
        publish(run_id)
        print("Published", run_id)
