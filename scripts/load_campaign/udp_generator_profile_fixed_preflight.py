#!/usr/bin/env python3
"""Disposable sampler validation only; never starts a game or bot workload."""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

from udp_generator_profile import profile_failure
from udp_generator_profile_record import record
from udp_generator_profile_decode import decode


def validate_status(observation, now_ns):
    problem = profile_failure(observation, now_ns)
    if problem:
        raise RuntimeError('Shared sampler gate: ' + problem)


def main(directory):
    p = pathlib.Path(directory)
    p.mkdir(exist_ok=False)
    binary = pathlib.Path('/home/deploy/omega-results/udp-generator-profile-tools-20261021/validation/busy')
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    if expected != 'b75b02e9e2a4eed95d75f07b01ae691aa122ddcdcee2af414687f419590cabc7':
        raise RuntimeError('Prior disposable executable changed')
    provenance = subprocess.run(['perf', 'version'], capture_output=True, text=True,
                                check=True, timeout=3).stdout
    child = subprocess.Popen([str(binary)])
    try:
        record(child.pid, p/'recording', time.time_ns()-22*10**9, 0, expected)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
    status = json.loads((p/'recording/profile-status.json').read_text())
    observation = {'profiles': {'disposable': status}, 'profile_supervisor': {}}
    validate_status(observation, time.time_ns())
    decode(p/'recording')
    decoded = json.loads((p/'recording/decode-summary.json').read_text())
    blocks = [b for b in (p/'recording/perf-script.txt').read_text().split('\n\n') if 'cpu-clock' in b]
    complete = sum(all(n in b for n in ('leaf', 'middle', 'outer', 'main')) for b in blocks)
    counts = decoded['record_counts']
    valid = (len(blocks) >= 100 and complete >= .8*len(blocks)
             and decoded['script_rc'] == decoded['raw_rc'] == 0
             and counts['PERF_RECORD_SAMPLE'] == len(blocks)
             and all(v == 0 for k, v in counts.items() if k != 'PERF_RECORD_SAMPLE')
             and status['elapsed_s'] < 30 and status['file_bytes'] < 30*1024**2)
    result = {'observation': observation, 'shared_gate_passed': True,
              'samples': len(blocks), 'known_chain_samples': complete,
              'decode': decoded, 'validated': valid, 'disposable_exited': child.poll() is not None,
              'disposable_sha256': expected, 'perf_version': provenance.strip(),
              'utc_ns': time.time_ns()}
    (p/'validation.json').write_text(json.dumps(result, indent=2)+'\n')
    if not valid:
        raise RuntimeError('Disposable sample/decode/loss/stack validation failed')


if __name__ == '__main__':
    main(sys.argv[1])
