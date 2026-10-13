#!/usr/bin/env python3
"""Stop tcpdump first, then drain/flush the bounded flow recorder without losing its tail."""
import pathlib
import signal
import subprocess
import sys

directory = pathlib.Path(sys.argv[1])
with (directory / "capture.log").open("w") as log:
    capture = subprocess.Popen(["tcpdump", "-i", "eth0", "-n", "-s", "0", "-B", "32768", "-U", "-w", "-", "udp", "port", "8081"], stdout=subprocess.PIPE, stderr=log)
    recorder = subprocess.Popen([str(directory.parents[1] / "flow-record"), str(directory)], stdin=capture.stdout, stderr=log)
    capture.stdout.close()

    def stop(*_):
        capture.send_signal(signal.SIGINT)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    capture.wait()
    result = recorder.wait()
    sys.exit(result)
