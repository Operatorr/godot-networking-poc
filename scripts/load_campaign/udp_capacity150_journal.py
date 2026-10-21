#!/usr/bin/env python3
"""Recover bounded logs from the finished observation; no service or workload actions.

Journald can encode MESSAGE as a byte array, not a JSON string. Preserve raw rows,
normalize that field only for counting, and retain a separate checksummed supplement.
"""
import gzip
import hashlib
import json
import pathlib
import shlex
import subprocess
import sys
import time

NAMESPACE='udp-capacity150-20261021'
REMOTE='/home/deploy/omega-results/'+NAMESPACE

def message(row):
    value=row.get('MESSAGE','')
    return bytes(value).decode('utf-8','replace') if isinstance(value,list) else value

def remote(since,until):
    directory=pathlib.Path(REMOTE)/'journal-supplement'
    directory.mkdir(exist_ok=False)
    process=subprocess.Popen(['journalctl','-u','omega-loadtest-arena.service','--since','@'+str(since/1e9),'--until','@'+str(until/1e9),'--no-pager','-o','json'],stdout=subprocess.PIPE)
    total=retained=seen_bytes=0;counts={};first={};invocations=set();dropped=0;arrays=0
    with gzip.open(directory/'game-journal.ndjson.gz','xb') as output:
        for line in process.stdout:
            row=json.loads(line);msg=message(row);arrays+=isinstance(row.get('MESSAGE'),list)
            invocations.add(row.get('_SYSTEMD_INVOCATION_ID'));total+=1;seen_bytes+=len(line)
            for key in ('panicked','oversized','decode','send','disconnect','timed out','suppressed'):
                if key in msg.lower():
                    counts[key]=counts.get(key,0)+1
                    first.setdefault(key,{'utc_us':row.get('__REALTIME_TIMESTAMP'),'message':msg})
            if retained+len(line)<=24*1024**2:
                output.write(line);retained+=len(line)
            else:dropped+=1
    rc=process.wait(timeout=10)
    summary={'records':total,'retained_bytes':retained,'seen_bytes':seen_bytes,'bounded_bytes':24*1024**2,'dropped_from_retention':dropped,'message_byte_arrays':arrays,'invocations':sorted(x for x in invocations if x),'counts':counts,'first_findings':first,'exit_code':rc,'complete':rc==0 and dropped==0,'since_ns':since,'until_ns':until}
    (directory/'journal-summary.json').write_text(json.dumps(summary,indent=2)+'\n')

def local():
    import run
    path=run.ROOT/'deployment/hetzner/results'/NAMESPACE
    manifest=json.loads((path/'manifest.json').read_text())
    start=manifest['experiment_service_start_ns'];end=manifest['game_stopped_utc_ns']
    host=run.HOSTS['game']
    upload=subprocess.run(['scp','-q','-i',str(run.KEY),*run.SSH_OPTIONS,str(pathlib.Path(__file__)),host['ssh_user']+'@'+host['ipv4']+':'+REMOTE+'/udp_capacity150_journal.py'],capture_output=True,text=True)
    if upload.returncode:raise RuntimeError('Supplement helper upload failed')
    cmd='python3 '+REMOTE+'/udp_capacity150_journal.py remote '+str(start)+' '+str(end)
    (path/'journal-supplement-command.txt').write_text(cmd+'\n')
    run.ssh('game',cmd)
    run.ssh('game','tar -czf '+REMOTE+'/game-journal-supplement.tar.gz -C '+REMOTE+' journal-supplement')
    run.copy('game',REMOTE+'/game-journal-supplement.tar.gz',path/'game-journal-supplement.tar.gz',download=True)
    remote_hash=run.ssh('game','sha256sum '+REMOTE+'/game-journal-supplement.tar.gz').split()[0]
    local_hash=hashlib.sha256((path/'game-journal-supplement.tar.gz').read_bytes()).hexdigest()
    if remote_hash!=local_hash:raise RuntimeError('Supplement checksum mismatch')
    (path/'journal-supplement-verification.json').write_text(json.dumps({'utc_ns':time.time_ns(),'local_sha256':local_hash,'remote_sha256':remote_hash,'equal':True,'retained_remote':True},indent=2)+'\n')
    print('Finished-observation journal supplement retained and independently checksum-verified')

if __name__=='__main__':
    try:
        if len(sys.argv)>1 and sys.argv[1]=='remote':remote(int(sys.argv[2]),int(sys.argv[3]))
        else:local()
    except Exception as error:
        print('Journal supplement failed: '+type(error).__name__,file=sys.stderr)
        sys.exit(1)
