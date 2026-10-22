#!/usr/bin/env python3
"""Bound existing compact capture to 300 seconds, 48 MiB retained and 512 MiB cgroup."""
import json
import pathlib
import resource
import signal
import subprocess
import sys
import time

root = pathlib.Path(__file__).parent
directory = pathlib.Path(sys.argv[1])
started = time.monotonic()
stopped = False

def stop(*_):
    global stopped
    stopped = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
child = subprocess.Popen([sys.executable, str(root / 'capture.py'), *sys.argv[1:], '--article'])
reason = 'capture-exit'
maximum = 0
try:
    while child.poll() is None:
        retained = sum(p.stat().st_size for p in directory.iterdir() if p.name in
                       ('port-bot.csv', 'flow-bins.csv', 'datagrams.bin', 'flow-points.csv', 'input-ports.csv', 'capture.log', 'flow-summary.json'))
        maximum = max(maximum, retained)
        if stopped or time.monotonic() - started >= 300 or retained >= 48 * 1024**2:
            reason = 'controller-stop' if stopped else ('time-limit' if time.monotonic() - started >= 300 else 'size-limit')
            break
        time.sleep(.25)
finally:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            reason += '-forced'
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    own = resource.getrusage(resource.RUSAGE_SELF)
    (directory / 'capture-resource.json').write_text(json.dumps({
        'reason': reason, 'exit_code': child.returncode, 'elapsed_s': time.monotonic()-started,
        'children_cpu_s': usage.ru_utime+usage.ru_stime, 'self_cpu_s': own.ru_utime+own.ru_stime,
        'children_maxrss_kib': usage.ru_maxrss, 'max_retained_sampled_bytes': maximum,
        'retained_limit_bytes':48*1024**2, 'cgroup_memory_max_bytes':512*1024**2,
        'file_limit_bytes':64*1024**2, 'time_limit_s':300})+'\n')
