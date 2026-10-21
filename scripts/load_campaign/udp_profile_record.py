#!/usr/bin/env python3
"""Bounded remote CPU recorder; no workload or system configuration changes."""
import argparse
import json
import os
import pathlib
import resource
import select
import signal
import subprocess
import time


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def record(pid, directory, seconds=58):
    directory = pathlib.Path(directory)
    output = directory / 'perf.data'
    if output.exists():
        raise RuntimeError('Profile already exists; refusing overwrite')
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    control_r, control_w = os.pipe()
    ack_r, ack_w = os.pipe()
    argv = ['perf', 'record', '-e', 'cpu-clock', '-F', '99', '-p', str(pid),
            '--call-graph', 'dwarf,8192', '-k', 'mono', '-T', '--sample-cpu',
            '--no-buildid-cache', '--max-size=60M', '-m', '256', '-D', '-1',
            '--control=fd:' + str(control_r) + ',' + str(ack_w), '-o', str(output)]
    env = dict(os.environ, DEBUGINFOD_URLS='')
    started = time.monotonic()
    status = dict(target_pid=pid, argv=argv, started_utc_ns=time.time_ns(),
                  started_monotonic_ns=time.monotonic_ns(), duration_limit_s=seconds,
                  file_limit_bytes=64 * 1024**2, samples_enabled=False)
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    with (directory / 'perf-record.log').open('x') as log:
        child = subprocess.Popen(argv, stdout=log, stderr=log, env=env,
                                 pass_fds=(control_r, ack_w), preexec_fn=limits)
        os.close(control_r)
        os.close(ack_w)
        status['profiler_pid'] = child.pid
        reason = 'duration-limit'
        try:
            os.write(control_w, b'enable\n')
            acknowledgement = b''
            ack_deadline = time.monotonic() + 8
            while b'ack\n' not in acknowledgement and time.monotonic() < ack_deadline:
                if not select.select([ack_r], [], [], max(0, ack_deadline - time.monotonic()))[0]:
                    break
                chunk = os.read(ack_r, 64)
                if not chunk:
                    break
                acknowledgement += chunk
            status['enable_ack_hex'] = acknowledgement.hex()
            if b'ack\n' not in acknowledgement:
                raise RuntimeError('perf enable acknowledgement absent; inspect perf-record.log')
            status['samples_enabled'] = True
            status['enabled_utc_ns'] = time.time_ns()
            status['enabled_monotonic_ns'] = time.monotonic_ns()
            dump(directory / 'profile-ready.json', status)
            with (directory / 'profile-clock.ndjson').open('x') as clocks:
                while child.poll() is None and time.monotonic() - started < seconds:
                    row = {'utc_ns': time.time_ns(), 'monotonic_ns': time.monotonic_ns()}
                    for name, process in (('target', pid), ('profiler', child.pid)):
                        try:
                            row[name + '_stat'] = pathlib.Path('/proc', str(process), 'stat').read_text()
                        except FileNotFoundError:
                            row[name + '_stat'] = None
                    clocks.write(json.dumps(row) + '\n')
                    clocks.flush()
                    if stopped:
                        reason = 'controller-stop'
                        break
                    if row['target_stat'] is None:
                        reason = 'target-exited'
                        break
                    if output.exists() and output.stat().st_size >= 60 * 1024**2:
                        reason = 'size-guard'
                        break
                    time.sleep(.1)
                if child.poll() is not None:
                    reason = 'perf-exited'
        except Exception as error:
            status['error'] = str(error)
            raise
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    reason = 'forced-kill'
            os.close(control_w)
            os.close(ack_r)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            status.update(reason=reason, rc=child.returncode,
                          elapsed_s=time.monotonic() - started, ended_utc_ns=time.time_ns(),
                          profiler_user_cpu_s=usage.ru_utime, profiler_system_cpu_s=usage.ru_stime,
                          file_bytes=output.stat().st_size if output.exists() else 0)
            own = resource.getrusage(resource.RUSAGE_SELF)
            status['supervisor_cpu_s'] = own.ru_utime + own.ru_stime
            dump(directory / 'profile-status.json', status)
    return status


def validate(directory):
    directory = pathlib.Path(directory)
    directory.mkdir(mode=0o700)
    source = directory / 'busy.c'
    source.write_text('''#include <stdint.h>
#include <unistd.h>
volatile uint64_t sink;
__attribute__((noinline)) void leaf(void) { for (uint64_t i=0;i<1000000;i++) sink = sink*1664525+i+1013904223; }
__attribute__((noinline)) void middle(void) { leaf(); sink++; }
__attribute__((noinline)) void outer(void) { for (;;) middle(); }
int main(void) { alarm(10); outer(); return 0; }
''')
    binary = directory / 'busy'
    subprocess.run(['cc', '-O2', '-fomit-frame-pointer', '-fasynchronous-unwind-tables',
                    '-fno-optimize-sibling-calls', '-o', str(binary), str(source)], check=True)
    child = subprocess.Popen([str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        status = record(child.pid, directory, 3)
    finally:
        child.terminate()
        child.wait(timeout=3)
    with (directory / 'stacks.txt').open('x') as stacks, (directory / 'decode.log').open('x') as log:
        subprocess.run(['perf', 'script', '-i', str(directory / 'perf.data'), '--ns',
                        '-F', 'comm,pid,tid,time,event,ip,sym,dso,period'],
                       stdout=stacks, stderr=log, check=True, timeout=20,
                       env=dict(os.environ, DEBUGINFOD_URLS=''))
    text = (directory / 'stacks.txt').read_text()
    blocks = [b for b in text.split('\n\n') if 'cpu-clock' in b]
    complete = sum(all(name in b for name in ('leaf', 'middle', 'outer', 'main')) for b in blocks)
    status.update(samples=len(blocks), known_chain_samples=complete,
                  validated=status['samples_enabled'] and len(blocks) >= 100 and complete >= .8 * len(blocks))
    dump(directory / 'validation.json', status)
    print(json.dumps({k: status[k] for k in ('samples', 'known_chain_samples', 'validated', 'rc', 'file_bytes')}))
    return 0 if status['validated'] else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('record', 'validate'))
    parser.add_argument('--directory', required=True)
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    if args.mode == 'validate':
        raise SystemExit(validate(args.directory))
    record(args.pid, args.directory)
