"""Stream the bounded experiment journal; retain a prefix and complete compact counts."""
import collections
import json
import pathlib
import re
import subprocess

def message(row):
    value=row.get('MESSAGE','')
    return bytes(value).decode('utf-8','replace') if isinstance(value,list) else value

def scan(lines, output, periods, limit=24*1024**2):
    counts={name:collections.Counter() for name in periods};seconds={};first={};invocations=set()
    result={'records':0,'retained_bytes':0,'seen_bytes':0,'dropped_from_retention':0,'message_byte_arrays':0,'bounded_bytes':limit}
    retaining=True
    for line in lines:
        row=json.loads(line);msg=message(row);stamp=int(row['__REALTIME_TIMESTAMP'])*1000
        result['records']+=1;result['seen_bytes']+=len(line);result['message_byte_arrays']+=isinstance(row.get('MESSAGE'),list)
        invocations.add(row.get('_SYSTEMD_INVOCATION_ID'));lower=msg.lower()
        categories=['records']+[k for k in ('panicked','oversized','decode','send','disconnect','timed out','suppressed') if k in lower]
        for name,(a,b) in periods.items():
            if a<=stamp<b:counts[name].update(categories)
        seconds.setdefault(stamp//10**9,collections.Counter()).update(categories)
        for key in categories[1:]:first.setdefault(key,{'utc_ns':stamp,'message':msg[:4096]})
        if retaining and result['retained_bytes']+len(line)<=limit:
            output.write(line);result['retained_bytes']+=len(line)
        else:
            retaining=False;result['dropped_from_retention']+=1
    result.update(invocations=sorted(x for x in invocations if x),first_findings=first,
                  periods={k:{'start_ns':v[0],'end_ns':v[1],'counts':dict(counts[k])} for k,v in periods.items()},
                  seconds=[{'utc_second':s,**dict(c)} for s,c in sorted(seconds.items())],
                  complete=result['dropped_from_retention']==0)
    return result

def export(directory, since, until):
    d=pathlib.Path(directory);periods={'experiment':(since,until)}
    if (d/'window.json').exists():
        w=json.loads((d/'window.json').read_text());periods['steady_window']=(w['start'],w['end'])
    if (d/'workload-period.json').exists():periods['full_workload']=json.loads((d/'workload-period.json').read_text())
    proc=subprocess.Popen(['journalctl','-u','omega-loadtest-arena.service','--since','@'+str(since/1e9),
                           '--until','@'+str(until/1e9),'--no-pager','-o','json'],stdout=subprocess.PIPE)
    try:
        with (d/'game-journal.ndjson').open('xb') as output:result=scan(proc.stdout,output,periods)
        result['exit_code']=proc.wait(timeout=10);result['complete_scan']=result['exit_code']==0
        (d/'journal-summary.json').write_text(json.dumps(result)+'\n')
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
