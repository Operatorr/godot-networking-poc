#!/usr/bin/env python3
"""One bounded offline decode of retained data; never launch or record a workload."""
import hashlib
import json
import pathlib
import shlex
import sys
import tarfile
import time
import run

P=run.ROOT/'deployment/hetzner/results/udp-generator-profile-fixed-20261021'
REMOTE='/home/deploy/omega-results/udp-generator-profile-fixed-20261021'

def main():
    proof=json.loads((P/'final-verification-summary.json').read_text())
    if any(v is False for role in proof.values() for v in role.values()):raise RuntimeError('Cleanup proof failed')
    if (P/'offline-reserved.json').exists():raise RuntimeError('Offline decode already reserved; inspect retained evidence')
    (P/'offline-reserved.json').write_text(json.dumps({'utc_ns':time.time_ns()}))
    # Materialize primary evidence first; supplementary decoding must not make a
    # partial bots/ directory that later looks like a fully extracted archive.
    for role in ('game','bots'):
        with tarfile.open(P/(role+'.tar.gz')) as archive:
            archive.extractall(P/'extracted',filter='data')
    source=run.ROOT/'scripts/load_campaign/udp_generator_profile_decode.py'
    (P/'udp_generator_profile_decode.executed.py').write_bytes(source.read_bytes())
    run.copy('bots',source,REMOTE+'/udp_generator_profile_decode.py')
    commands=[]
    def ssh(cmd):
        commands.append(cmd);(P/'offline-commands.json').write_text(json.dumps(commands,indent=2))
        return run.ssh('bots',cmd)
    names=['perf-script.txt','perf-script.log','perf-records.txt.gz','perf-records.log','decode-summary.json','poll-annotate.txt','poll-annotate.log','poll-annotate.exit','executable-sections.txt','executable-symbols.txt']
    archived=[]
    for name in ('early','late'):
        # Only decode retained recordings; an absent profile is missing evidence.
        if ssh('test -f '+REMOTE+'/bots/'+name+'/perf.data && echo yes || true').strip() != 'yes':
            continue
        d=REMOTE+'/bots/'+name
        ssh('timeout 65s python3 '+REMOTE+'/udp_generator_profile_decode.py '+d)
        binary='/home/deploy/omega-udp-control-cc86869/rust/target/release/omega-load-test'
        command='ulimit -f 65536; export DEBUGINFOD_URLS=; timeout 45s perf annotate --stdio --no-source -i '+d+'/perf.data -s '+shlex.quote('omega_load_test::bot::Bot::poll')+' > '+d+'/poll-annotate.txt 2> '+d+'/poll-annotate.log; echo $? > '+d+'/poll-annotate.exit; timeout 15s readelf -SW '+binary+' > '+d+'/executable-sections.txt; timeout 15s nm -n -C --defined-only '+binary+' > '+d+'/executable-symbols.txt'
        ssh(command)
        archived.extend('bots/'+name+'/'+n for n in names)
    if not archived:raise RuntimeError('No retained profile to decode')
    ssh('tar -czf '+REMOTE+'/offline.tar.gz -C '+REMOTE+' '+' '.join(archived)+' udp_generator_profile_decode.py')
    run.copy('bots',REMOTE+'/offline.tar.gz',P/'offline.tar.gz',download=True)
    expected=ssh('sha256sum '+REMOTE+'/offline.tar.gz').split()[0]
    actual=hashlib.sha256((P/'offline.tar.gz').read_bytes()).hexdigest()
    if expected!=actual:raise RuntimeError('Offline archive mismatch')
    (P/'offline-verification.json').write_text(json.dumps({'remote_sha256':expected,'local_sha256':actual,'equal':True,'utc_ns':time.time_ns(),'remote_retained':True},indent=2))
    with tarfile.open(P/'offline.tar.gz') as archive:archive.extractall(P/'extracted',filter='data')
    print('Offline evidence decoded and SHA-256 verified; no workload launched')

if __name__=='__main__':
    try:main()
    except Exception as error:
        (P/'offline-error.txt').write_text(str(error));print('Offline evidence failure: '+type(error).__name__,file=sys.stderr);sys.exit(1)
