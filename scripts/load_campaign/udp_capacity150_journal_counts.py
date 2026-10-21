#!/usr/bin/env python3
"""Bounded summaries over finished-run journald records; no live instrumentation."""
import collections
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
from udp_capacity150_journal import message, NAMESPACE, REMOTE

def remote(spec):
    spec=json.loads(spec);summary={'periods':{},'invocations':[],'records_scanned':0,'first':{},'max_message_bytes':0}
    limits=spec['periods'];counts={name:collections.Counter() for name in limits};sizes={name:[] for name in limits};by_second={};invocations=set();first={}
    process=subprocess.Popen(['journalctl','-u','omega-loadtest-arena.service','--since','@'+str(spec['start']/1e9),'--until','@'+str(spec['end']/1e9),'--no-pager','-o','json','--output-fields=__REALTIME_TIMESTAMP,_SYSTEMD_INVOCATION_ID,MESSAGE'],stdout=subprocess.PIPE)
    # One row per observed second; no per-warning retention or unbounded samples.
    for line in process.stdout:
        row=json.loads(line);text=message(row);stamp=int(row['__REALTIME_TIMESTAMP'])*1000;lower=text.lower();summary['records_scanned']+=1
        invocations.add(row.get('_SYSTEMD_INVOCATION_ID'));summary['max_message_bytes']=max(summary['max_message_bytes'],len(text.encode()))
        categories=[key for key in ('oversized','panicked','decode','send','disconnect','timed out','suppressed') if key in lower]
        byte_match=re.search(r'oversized unreliable packet \((\d+) B\)',text)
        for name,(a,b) in limits.items():
            if not a<=stamp<b:continue
            counts[name]['records']+=1
            for key in categories:counts[name][key]+=1
            if byte_match:
                n=int(byte_match[1]);old=sizes[name];sizes[name]=[min(n,old[0]) if old else n,max(n,old[1]) if old else n]
        current=by_second.setdefault(stamp//10**9,collections.Counter())
        current['records']+=1
        for key in categories:
            current[key]+=1
            first.setdefault(key,{'utc_ns':stamp,'message':text})
    rc=process.wait(timeout=10)
    summary.update(exit_code=rc,complete_scan=rc==0,invocations=sorted(x for x in invocations if x),first=first,
        periods={name:{'start_ns':a,'end_ns':b,'counts':dict(counts[name]),'oversized_payload_bytes_min_max':sizes[name] or None} for name,(a,b) in limits.items()},
        seconds=[{'utc_second':sec,**dict(c)} for sec,c in sorted(by_second.items())])
    target=pathlib.Path(REMOTE)/'journal-counts.json'
    with target.open('x') as output:json.dump(summary,output)

def local():
    import run
    p=run.ROOT/'deployment/hetzner/results'/NAMESPACE;m=json.loads((p/'manifest.json').read_text());g=json.loads((p/'extracted/bots/guard-result.json').read_text());start=json.loads((p/'extracted/bots/workload-start.json').read_text())['utc_ns']
    spec={'start':m['experiment_service_start_ns'],'end':m['game_stopped_utc_ns'],'periods':{'experiment':[m['experiment_service_start_ns'],m['game_stopped_utc_ns']],'full_workload':[start,g['ended_utc_ns']],'steady_window':[m['window']['start'],m['window']['end']]}}
    host=run.HOSTS['game']
    import shlex
    upload=subprocess.run(['scp','-q','-i',str(run.KEY),*run.SSH_OPTIONS,str(pathlib.Path(__file__)),host['ssh_user']+'@'+host['ipv4']+':'+REMOTE+'/udp_capacity150_journal_counts.py'],capture_output=True,text=True)
    if upload.returncode:raise RuntimeError('Upload failed')
    command='python3 '+REMOTE+'/udp_capacity150_journal_counts.py remote '+shlex.quote(json.dumps(spec))
    (p/'journal-counts-command.txt').write_text(command+'\n')
    run.ssh('game',command)
    run.copy('game',REMOTE+'/journal-counts.json',p/'journal-counts.json',download=True)
    expected=run.ssh('game','sha256sum '+REMOTE+'/journal-counts.json').split()[0];actual=hashlib.sha256((p/'journal-counts.json').read_bytes()).hexdigest()
    if actual!=expected:raise RuntimeError('Count summary checksum mismatch')
    (p/'journal-counts-verification.json').write_text(json.dumps({'remote_sha256':expected,'local_sha256':actual,'equal':True,'utc_ns':time.time_ns(),'retained_remote':True},indent=2)+'\n')
    print('Bounded per-window journal counts checksum-verified; no workload launched')

if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='remote':remote(sys.argv[2])
        else:local()
    except Exception as error:
        print('Journal count recovery failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
