#!/usr/bin/env python3
"""Stop tcpdump first, then drain/flush the bounded flow recorder without losing its tail."""
import pathlib
import ipaddress
import signal
import subprocess
import sys

directory = pathlib.Path(sys.argv[1])
interface = sys.argv[2] if len(sys.argv) > 2 else "eth0"
if len(sys.argv) < 4:
    raise RuntimeError("Capture requires the test peer IPv4 address")
compact = "--article" in sys.argv[4:]
peer = str(ipaddress.IPv4Address(sys.argv[3]))
if any((directory / name).exists() for name in ('headers.pcap', 'datagrams.bin')):
    raise FileExistsError('Refusing to overwrite an existing capture generation')
with (directory / "capture.log").open("x") as log:
    capture = subprocess.Popen(["tcpdump", "-i", interface, "-n", "-s", "0", "-B", "32768", "-U", "-w", "-", "ip", "and", "udp", "and", "host", peer, "and", "port", "8081"], stdout=subprocess.PIPE, stderr=log)
    recorder_path = next(parent / "flow-record" for parent in directory.parents if (parent / "flow-record").exists())
    recorder = subprocess.Popen([str(recorder_path), str(directory)] + (["--article"] if compact else []), stdin=capture.stdout, stderr=log)
    capture.stdout.close()

    def stop(*_):
        capture.send_signal(signal.SIGINT)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    capture.wait()
    result = recorder.wait()
    sys.exit(result)
