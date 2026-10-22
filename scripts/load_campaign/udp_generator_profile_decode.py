#!/usr/bin/env python3
"""Offline decoding only, bounded to 60 s / 64 MiB per output; never records."""
import collections
import gzip
import json
import os
import pathlib
import re
import resource
import subprocess
import sys

def decode(directory):
    d=pathlib.Path(directory);env=dict(os.environ,DEBUGINFOD_URLS='');results={}
    def limits():resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    with (d/'perf-script.txt').open('x') as out,(d/'perf-script.log').open('x') as err:
        p=subprocess.run(['perf','script','-i',str(d/'perf.data'),'--ns','-F','comm,pid,tid,time,event,ip,sym,dso,period'],
                         stdout=out,stderr=err,env=env,preexec_fn=limits,timeout=60)
        results['script_rc']=p.returncode
    counts=collections.Counter({k:0 for k in ('PERF_RECORD_LOST','PERF_RECORD_LOST_SAMPLES','PERF_RECORD_THROTTLE','PERF_RECORD_UNTHROTTLE','PERF_RECORD_SAMPLE')})
    with gzip.open(d/'perf-records.txt.gz','xb') as out,(d/'perf-records.log').open('x') as err:
        p=subprocess.Popen(['timeout','60s','perf','script','-D','-i',str(d/'perf.data')],stdout=subprocess.PIPE,stderr=err,env=env,preexec_fn=limits)
        retained=0;scanned=0;dropped=0
        for line in p.stdout:
            for key in counts:
                if re.search(rb'\b'+key.encode()+rb'\b',line):counts[key]+=1
            scanned+=len(line)
            if retained+len(line)<=64*1024**2 and not dropped:
                out.write(line);retained+=len(line)
            else:dropped+=len(line)
        results.update(raw_rc=p.wait(timeout=5),raw_decoded_bytes=scanned,raw_retained_prefix_bytes=retained,raw_unretained_bytes=dropped,record_counts=dict(counts))
    (d/'decode-summary.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':decode(sys.argv[1])
