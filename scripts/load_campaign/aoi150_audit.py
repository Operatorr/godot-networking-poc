#!/usr/bin/env python3
"""Independent read-only final audit, including prebuild inventory preservation."""
import concurrent.futures
import hashlib
import json
import pathlib
import re
import subprocess
import time
import aoi150 as controller
import run
P=run.ROOT/'deployment/hetzner/results'/controller.NAMESPACE
B=run.ROOT/'deployment/hetzner/results'/(controller.NAMESPACE+'-build')

def audit():
    controller.verify()
    def one(role):
        before=json.loads((B/(role+'-before.json')).read_text())
        artifacts='\n'.join(line for line in before['artifacts'].splitlines())+'\n'
        # Only hash original paths from the immutable prebuild inventory.
        cmd='sha256sum '+ ' '.join(__import__('shlex').quote(line.split(None,1)[1]) for line in artifacts.splitlines())
        raw={}
        cmds={'original_artifacts':cmd,
              'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) ! -path '"+controller.REMOTE+"/*' -exec sha256sum {} \\; | sort",
              'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
              'maintenance':'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
              'collector_files':'cd '+controller.REMOTE+'/'+role+'; sha256sum -c collector-sha256.txt',
              'candidate_hash':'sha256sum '+controller.CANDIDATE_CHECKOUT+'/rust/target/release/omega-server',
              'candidate_source':'git -C '+controller.CANDIDATE_CHECKOUT+' rev-parse HEAD; git -C '+controller.CANDIDATE_CHECKOUT+' status --porcelain',
              'units':"systemctl list-units --all --no-legend 'omega-*'"}
        host=run.HOSTS[role]
        for key,command in cmds.items():
            proc=subprocess.run(['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,host['ssh_user']+'@'+host['ipv4'],command],capture_output=True,text=True,timeout=90)
            with (P/(role+'-independent-audit-commands.ndjson')).open('a') as f:
                f.write(json.dumps({'utc_ns':time.time_ns(),'command':command,'rc':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})+'\n')
            if proc.returncode:raise RuntimeError(role+' audit command failed; private details retained')
            raw[key]=proc.stdout
        result={'utc_ns':time.time_ns(),'all_prebuild_artifacts_preserved':raw['original_artifacts']==artifacts,
                'all_prebuild_archives_preserved':raw['prior_archives']==before['prior_archives'],
                'prebuild_closed_states_preserved':raw['closed_states']==before['closed_states'],
                'maintenance_matches_prebuild':raw['maintenance']==before['maintenance'],
                'collector_files_match_retained_hashes':bool(raw['collector_files']) and all(line.endswith(': OK') for line in raw['collector_files'].splitlines()),
                'candidate_hash_matches':raw['candidate_hash'].split()[0]==controller.EXPECTED_CANDIDATE,
                'candidate_source_exact_and_clean':raw['candidate_source'].strip()==controller.CANDIDATE_REVISION,
                'no_owned_active_units':not any(controller.NAMESPACE in line and re.search(r'\sactive\s',line) for line in raw['units'].splitlines())}
        (P/(role+'-independent-audit-raw.json')).write_text(json.dumps(raw,indent=2))
        return result
    with concurrent.futures.ThreadPoolExecutor(2) as pool:result=dict(zip(('game','bots'),pool.map(one,('game','bots'))))
    (P/'independent-prebuild-preservation-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    assert all(v is not False for r in result.values() for v in r.values()),'Independent prebuild preservation check failed'
    print('Independent audit passed: prebuild artifacts, archives, closed state, maintenance, candidate and collectors preserved')

if __name__=='__main__':
    try:audit()
    except Exception as e:
        (P/'independent-audit-error.json').write_text(json.dumps({'type':type(e).__name__,'error':str(e),'utc_ns':time.time_ns()}))
        print('Independent audit failed; private details retained')
        raise SystemExit(1)
