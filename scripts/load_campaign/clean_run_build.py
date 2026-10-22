#!/usr/bin/env python3
"""Inventory idle hosts and build an exact revision in a fresh namespace; never run it."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--namespace', default='clean-strategy150-r1-20261022')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Full immutable revision required')
    if not re.fullmatch(r'clean-[a-z0-9-]{1,65}', args.namespace):
        parser.error('Invalid namespace')
    assert subprocess.check_output(['git','branch','--show-current'],text=True).strip() == 'fix/load-test-clean-runs'
    assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip() == args.revision
    os.umask(0o077)
    directory = run.ROOT/'deployment/hetzner/results'/(args.namespace+'-build')
    directory.mkdir(mode=0o700,exist_ok=False)
    dest = '/home/deploy/omega-' + args.namespace
    remote_bundle = '/home/deploy/' + args.namespace + '.bundle'

    def ssh(role, command, timeout=90):
        host = run.HOSTS[role]
        try:
            result = subprocess.run(['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,
                                     host['ssh_user']+'@'+host['ipv4'],command],
                                    capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            (directory/(role+'-timeout.json')).write_text(json.dumps(dict(command=command,stdout=str(error.stdout),stderr=str(error.stderr))))
            raise RuntimeError(role+' timed out; private exact output retained') from None
        with (directory/(role+'-commands.ndjson')).open('a') as stream:
            stream.write(json.dumps(dict(utc_ns=time.time_ns(),command=command,rc=result.returncode,
                                         stdout=result.stdout,stderr=result.stderr))+'\n')
        if result.returncode:
            raise RuntimeError(role+' remote failure; exact private journal retained')
        return result.stdout

    def inventory(role):
        commands = {
            'processes':'ps -eo pid,comm,args',
            'units':"systemctl list-units --all --no-legend 'omega-*'",
            'disk':'df --output=avail -B1 /home/deploy | tail -1',
            'buffers':'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
            'toolchain':'source /home/deploy/.cargo/env; rustc -Vv; cargo -V; uname -a',
            'build_environment':"env | sort | sed -n '/^RUST/p; /^CARGO/p; /^CC=/p; /^CFLAGS=/p; /^LDFLAGS=/p'",
            'cargo_config':"for p in /home/deploy/.cargo/config /home/deploy/.cargo/config.toml; do if test -f $p; then cat $p; fi; done",
            'artifacts':"find /home/deploy/omega-* -maxdepth 5 -path '*/target/release/omega-*' -type f ! -name '*.d' -exec sha256sum {} \\; | sort",
            'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",
            'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
            'namespace_absent':'test ! -e /home/deploy/omega-results/'+args.namespace+' && test ! -e '+dest+' && echo absent',
            'maintenance':'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
            'qdisc':'tc -j qdisc show dev eth0','egress':'tc -j filter show dev eth0 egress',
            'ingress':'tc -j filter show dev eth0 ingress','nft':'sudo -n nft list ruleset',
        }
        if role == 'game':
            commands.update(metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',
                config='sha256sum /etc/omega-loadtest/arena.json',service='systemctl is-active omega-loadtest-arena.service',
                exe='pid=$(systemctl show omega-loadtest-arena.service -p MainPID --value); sha256sum /proc/$pid/exe',
                sockets='sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"',unit='systemctl cat omega-loadtest-arena.service')
        data = {key:ssh(role,command) for key,command in commands.items()}
        (directory/(role+'-before.json')).write_text(json.dumps(data,indent=2))
        assert int(data['disk']) > 8*1024**3, role+' disk guard'
        assert not any(' active ' in line and any(x in line for x in ('swarm','capture','collect','restore.timer')) for line in data['units'].splitlines()), 'active ownership'
        assert 'rustc 1.95.0' in data['toolchain'] and 'host: aarch64-unknown-linux-gnu' in data['toolchain']
        assert not data['build_environment'].strip() and not data['cargo_config'].strip(), 'nonbaseline compiler environment'
        for line in data['processes'].splitlines()[1:]:
            parts = line.split(None,2)
            if len(parts)<3 or parts[1] in ('bash','sshd','sshd-session'):continue
            assert parts[1] not in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') and not any(x in parts[2] for x in ('host_collect.py','capture.py','flow-record','udp_generator_profile')), 'occupied host'
        for block in data['maintenance'].split('\n\n'):
            if 'Id=apt-daily.service' in block or 'Id=apt-daily-upgrade.service' in block:assert 'ActiveState=inactive' in block
        assert not json.loads(data['egress']) and not json.loads(data['ingress'])
        assert all(q['kind']=='fq_codel' for q in json.loads(data['qdisc'])) and 'omega_measure' not in data['nft']
        if role == 'game':
            assert re.search(r'^players_online 0$',data['metrics'],re.M)
            assert data['service'].strip()=='active' and data['exe'].split()[0]=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2'
            assert data['config'].split()[0]=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c'
            assert 'rb524288' in data['sockets'] and 'tb524288' in data['sockets']
        print(role+' idle/unclaimed inventory passed',flush=True)

    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(inventory,('game','bots')))
        bundle = directory/'candidate.bundle'
        subprocess.run(['git','bundle','create',str(bundle),'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb..HEAD'],check=True,capture_output=True)
        source = dict(revision=args.revision,tree=subprocess.check_output(['git','rev-parse',args.revision+'^{tree}'],text=True).strip(),
                      bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                      source_archive_sha256=hashlib.sha256(subprocess.check_output(['git','archive',args.revision])).hexdigest(),
                      local_utc_ns=time.time_ns())
        (directory/'toolchain-and-source-proof.json').write_text(json.dumps(source,indent=2))
        def build(role):
            run.copy(role,bundle,remote_bundle)
            command = ('set -e; source /home/deploy/.cargo/env; test ! -e {d}; '
                'git clone --shared --no-checkout /home/deploy/omega-udp-control-cc86869 {d}; '
                'git -C {d} fetch {b} HEAD; git -C {d} checkout --detach {r}; '
                'test -z "$(git -C {d} status --porcelain)"; test "$(git -C {d} rev-parse HEAD)" = {r}; '
                'cd {d}/rust; rustc -Vv; cargo -V; uname -a; '
                'cargo build --release --locked -j 2 -p omega-server -p omega-load-test; '
                'sha256sum target/release/omega-server target/release/omega-load-test; '
                'git status --porcelain').format(d=dest,b=remote_bundle,r=args.revision)
            output=ssh(role,command,1200)
            proof=dict(revision=args.revision,path=dest,sha256=ssh(role,'sha256sum '+dest+'/rust/target/release/omega-server').split()[0],
                       bot_sha256=ssh(role,'sha256sum '+dest+'/rust/target/release/omega-load-test').split()[0],
                       build_argv=['cargo','build','--release','--locked','-j','2','-p','omega-server','-p','omega-load-test'],
                       build_stdout=output,utc_ns=time.time_ns())
            (directory/(role+'-build.json')).write_text(json.dumps(proof,indent=2))
            print(role+' pinned release build passed',flush=True)
            return proof
        with concurrent.futures.ThreadPoolExecutor(2) as pool:proofs=dict(zip(('game','bots'),pool.map(build,('game','bots'))))
        assert all(proofs['game'][k]==proofs['bots'][k] for k in ('revision','sha256','bot_sha256','path'))
        (directory/'build-proof.json').write_text(json.dumps(proofs,indent=2))
        print('Both-host candidate identities agree; zero workloads launched',flush=True)
    except Exception as error:
        (directory/'failure.json').write_text(json.dumps(dict(type=type(error).__name__,error=str(error))))
        print('Build/preflight blocked: '+str(error),file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
