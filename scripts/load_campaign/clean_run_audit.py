#!/usr/bin/env python3
"""Independent read-only preservation audit against the prebuild inventory."""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import time

import run


def hashes(text):
    result={}
    for line in text.splitlines():
        digest,path=line.split(None,1)
        if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Invalid checksum row')
        if path in result:raise ValueError('Duplicate checksum path')
        result[path]=digest
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',default='clean-strategy150-r1-20261022')
    args=parser.parse_args()
    if not re.fullmatch(r'clean-[a-z0-9-]{1,65}',args.namespace):parser.error('Invalid namespace')
    local=run.ROOT/'deployment/hetzner/results'/args.namespace
    build=local.with_name(args.namespace+'-build')
    results={}
    for role in ('game','bots'):
        before=json.loads((build/(role+'-before.json')).read_text())
        commands={
            'artifacts':"find /home/deploy/omega-* -maxdepth 5 -path '*/target/release/omega-*' -type f ! -name '*.d' -exec sha256sum {} \\; | sort",
            'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",
            'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
            'units':"systemctl list-units --all --no-legend 'omega-*'",
            'queues':'sudo -n ss -u -a -m -n -p -e',
        }
        raw={}
        for key,command in commands.items():
            host=run.HOSTS[role]
            result=subprocess.run(['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,host['ssh_user']+'@'+host['ipv4'],command],capture_output=True,text=True,timeout=90)
            raw[key]=dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
            (local/(role+'-independent-preservation-raw.json')).write_text(json.dumps(raw,indent=2))
            if result.returncode:raise RuntimeError(role+' audit command failed; exact private evidence retained')
        checks={key:all(hashes(raw[key]['stdout']).get(path)==digest for path,digest in hashes(before[key]).items())
                for key in ('artifacts','prior_archives','closed_states')}
        active=[line for line in raw['units']['stdout'].splitlines() if re.search(r'\sactive\s',line) and not (role=='game' and line.strip().startswith('omega-loadtest-arena.service '))]
        checks['no_active_other_workload_units']=not active
        checks['no_bot_sockets']='omega-load-test' not in raw['queues']['stdout']
        checks['queues_quiet']=all(int(v)==0 for pair in re.findall(r'UNCONN\s+(\d+)\s+(\d+)\s+.*omega-',raw['queues']['stdout']) for v in pair)
        results[role]=dict(utc_ns=time.time_ns(),checks=checks,
            original_artifact_count=len(hashes(before['artifacts'])),
            original_archive_count=len(hashes(before['prior_archives'])),
            current_archive_sha256=hashlib.sha256((local/(role+'.tar.gz')).read_bytes()).hexdigest(),
            raw_sha256=hashlib.sha256((local/(role+'-independent-preservation-raw.json')).read_bytes()).hexdigest())
    (local/'independent-prebuild-preservation-audit.json').write_text(json.dumps(results,indent=2))
    if not all(all(row['checks'].values()) for row in results.values()):raise RuntimeError('Independent preservation/queue audit failed')
    print('Independent preservation and queue audit passed on both hosts')
    return results


if __name__=='__main__':main()
