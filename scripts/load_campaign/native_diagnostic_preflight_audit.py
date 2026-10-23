#!/usr/bin/env python3
"""Exclusive read-only idle/preservation audit when the diagnostic never staged/launched.

This is not a restoration/workload certificate. All calls are bounded and journaled.
"""
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import time
import clean_run_audit as audit
import clean_run_resources as resources
import run

NS='clean-idle150-audit-r1-20261022'


def main(label, namespace=NS):
    if namespace not in (NS,'clean-idle150-audit-r2-20261023','clean-idle150-audit-r3-20261023','clean-idle150-audit-r4-20261023','clean-idle150-audit-r5-20261023'):
        raise ValueError('Only the exact authorized unlaunched diagnostic namespaces')
    if not re.fullmatch(r'[a-z0-9-]{1,40}',label):raise ValueError('Invalid exclusive audit label')
    p=run.ROOT/'deployment/hetzner/results'/namespace
    pre=p.with_name(namespace+'-preflight');build=p.with_name(namespace+'-build')
    out=pre/(label+'-idle-audit.json');journal=pre/(label+'-idle-audit-commands.ndjson')
    if out.exists() or journal.exists():raise FileExistsError('Use a fresh audit label')
    if (p/'manifest.json').exists():raise ValueError('Not an unlaunched preflight')
    journal.touch(exist_ok=False)
    proofs={f.parent.name.removesuffix('-build'):json.loads(f.read_text()) for f in build.parent.glob('clean-*-build/build-proof.json')}
    result={}
    for role in ('game','bots'):
        baseline=json.loads((build/(role+'-before.json')).read_text())
        row_proofs={n:{k:r[role][k] for k in ('revision','path','sha256','bot_sha256')} for n,r in proofs.items()}
        module=pathlib.Path(resources.__file__).read_text()
        code=module+'\nimport json\nprint(json.dumps({n:candidate(r) for n,r in '+repr(row_proofs)+'.items()}))'
        commands={
            'clock':'date -u; chronyc tracking',
            'disk':'df --output=avail -B1 /home/deploy | tail -1',
            'source_and_top_level_hashes':'python3 -c '+shlex.quote(code),
            'artifacts':"find /home/deploy/omega-* -maxdepth 5 -path '*/target/release/omega-*' -type f ! -name '*.d' -exec sha256sum {} \\; | sort",
            'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",
            'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
            'units':"systemctl list-units --all --no-legend 'omega-*'",
            'processes':'ps -eo pid,comm,args',
            'queues':'sudo -n ss -u -a -m -n -p -e',
            'qdisc':'tc -j qdisc show dev eth0',
            'egress':'tc -j filter show dev eth0 egress',
            'ingress':'tc -j filter show dev eth0 ingress',
            'nft':'sudo -n nft list ruleset',
            'buffers':'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
            'maintenance':'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
            'namespace_absent':'test ! -e /home/deploy/omega-results/'+namespace+' && echo absent',
        }
        if role=='game':
            commands.update(
                config='sha256sum /etc/omega-loadtest/arena.json',
                unit='systemctl cat omega-loadtest-arena.service',
                environment='systemctl show omega-loadtest-arena.service -p Environment --value',
                active='systemctl is-active omega-loadtest-arena.service',
                exe='pid=$(systemctl show omega-loadtest-arena.service -p MainPID --value); sha256sum /proc/$pid/exe',
                metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',
                original_measurement_bytes='du -s -B1 /var/lib/omega-measure/current',
                original_measurement_backups=(
                    'set -e; count=0; for d in /home/deploy/omega-results/clean-*/original; do '
                    'if test -f "$d/measurement-verified"; then printf "BACKUP %s\\n" "$d"; '
                    '(cd "$d/measurement-current"; sha256sum -c ../measurement-sha256.txt); '
                    'count=$((count+1)); fi; done; test "$count" -gt 0'))
        raw={k:audit.bounded_ssh(role,c,journal) for k,c in commands.items()}
        checks={k:all(audit.hashes(raw[k]).get(path)==digest for path,digest in audit.hashes(baseline[k]).items())
                for k in ('artifacts','prior_archives','closed_states')}
        checks.update(source_and_top_level_hashes=bool(json.loads(raw['source_and_top_level_hashes'])),
            disk_above_8GiB=int(raw['disk'])>8*1024**3,
            diagnostic_never_staged=raw['namespace_absent'].strip()=='absent',
            native_qdisc=json.loads(raw['qdisc'])==json.loads(baseline['qdisc']),
            empty_filters=not json.loads(raw['ingress']) and not json.loads(raw['egress']),
            buffers_unchanged=raw['buffers']==baseline['buffers'],
            maintenance_unchanged=raw['maintenance']==baseline['maintenance'],
            no_bot_sockets='omega-load-test' not in raw['queues'],
            queues_quiet=all(int(v)==0 for pair in re.findall(r'UNCONN\s+(\d+)\s+(\d+)\s+.*omega-',raw['queues']) for v in pair))
        strip=lambda s:re.sub(r'counter packets \d+ bytes \d+','counter',s)
        checks['firewall_unchanged']=strip(raw['nft'])==strip(baseline['nft'])
        checks['no_active_workload_units']=not any(re.search(r'\sactive\s',line) and not (role=='game' and line.strip().startswith('omega-loadtest-arena.service ')) for line in raw['units'].splitlines())
        bad=[]
        for line in raw['processes'].splitlines()[1:]:
            parts=line.split(None,2)
            if len(parts)<3 or parts[1] in ('bash','sshd','sshd-session'):continue
            if parts[1] in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') or any(n in parts[2] for n in ('host_collect.py','capture.py','flow-record','udp_generator_profile')):bad.append(parts[0])
        checks['no_competing_or_owned_processes']=not bad
        if role=='game':
            checks.update(original_service_active=raw['active'].strip()=='active',
                original_executable=raw['exe'].split()[0]=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2',
                original_config=raw['config'].split()[0]=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c',
                original_unit=raw['unit']==baseline['unit'],
                diagnostic_environments_absent=all(n not in raw['environment'] for n in ('OMEGA_AOI_AUDIT=','OMEGA_NATIVE_DIAG=')),
                zero_players=bool(re.search(r'^players_online 0$',raw['metrics'],re.M)),
                ordinary_effective_buffers='rb524288' in raw['queues'] and 'tb524288' in raw['queues'],
                prior_measurement_backups_verified=bool(raw['original_measurement_backups']))
        raw_path=pre/(role+'-'+label+'-idle-raw.json')
        with raw_path.open('x') as stream:json.dump(raw,stream,indent=2)
        result[role]=dict(utc_ns=time.time_ns(),checks=checks,command_count=len(commands),
            failed_checks=[k for k,v in checks.items() if not v],raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            original_artifact_count=len(audit.hashes(baseline['artifacts'])),original_archive_count=len(audit.hashes(baseline['prior_archives'])),
            free_bytes=int(raw['disk']))
    summary=dict(label=label,scope='unlaunched preflight idle/preservation proof; no restoration or workload certificate',
        checks_pass=all(all(r['checks'].values()) for r in result.values()),hosts=result,
        commands_sha256=hashlib.sha256(journal.read_bytes()).hexdigest())
    with out.open('x') as stream:json.dump(summary,stream,indent=2)
    print(json.dumps(summary))
    if not summary['checks_pass']:raise RuntimeError('Idle preservation audit failed')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--label',required=True);p.add_argument('--namespace',default=NS)
    args=p.parse_args();main(args.label,args.namespace)
