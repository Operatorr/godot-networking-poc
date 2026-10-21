#!/usr/bin/env python3
"""Once-only Phase-2 generator sampler. No game sampling or workload launches."""
import argparse
import hashlib
import json
import os
import pathlib
import resource
import select
import signal
import subprocess
import time

EXPECTED = '831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3'
SOFT = 30 * 1024**2
HARD = 32 * 1024**2

def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')

def identity(pid):
    p=pathlib.Path('/proc')/str(pid)
    stat=(p/'stat').read_text()
    return {'pid':pid,'start_ticks':int(stat.rsplit(')',1)[1].split()[19]),
            'exe_sha256':hashlib.sha256((p/'exe').read_bytes()).hexdigest()}

def anchor(pid, recorder=None):
    row={'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns()}
    for name,number in (('target',pid),('profiler',recorder),('supervisor',os.getpid())):
        try:row[name+'_stat']=pathlib.Path('/proc',str(number),'stat').read_text() if number else None
        except FileNotFoundError:row[name+'_stat']=None
    return row

def record(pid, directory, phase, offset, expected=EXPECTED):
    directory=pathlib.Path(directory);directory.mkdir(exist_ok=False)
    started=time.monotonic();a=anchor(pid)
    nominal_start=phase+offset*10**9;nominal_end=nominal_start+25*10**9
    deadline=a['monotonic_ns']+(nominal_end-a['utc_ns'])
    status={'target_identity':identity(pid),'phase2_utc_ns':phase,'offset_s':offset,
            'nominal_start_ns':nominal_start,'nominal_end_ns':nominal_end,'initial_anchor':a,
            'clock_ticks_per_second':os.sysconf('SC_CLK_TCK'),'page_size':os.sysconf('SC_PAGE_SIZE'),
            'active_limit_s':25,'lifetime_limit_s':30,'soft_bytes':SOFT,'hard_bytes':HARD}
    if status['target_identity']['exe_sha256']!=expected:raise RuntimeError('Target hash mismatch')
    if a['utc_ns']>=nominal_end:
        status['error']='entire-window-missed';dump(directory/'profile-status.json',status);return
    output=directory/'perf.data';stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    cr,cw=os.pipe();ar,aw=os.pipe()
    argv=['perf','record','-e','cpu-clock','-F','99','-p',str(pid),'--call-graph','dwarf,8192',
          '-k','mono','-T','--sample-cpu','--no-buildid-cache','--max-size=30M','-m','256',
          '-D','-1','--control=fd:'+str(cr)+','+str(aw),'-o',str(output)]
    status['argv']=argv
    def limits():resource.setrlimit(resource.RLIMIT_FSIZE,(HARD,HARD))
    reason='nominal-window-end'
    with (directory/'perf-record.log').open('x') as log:
        child=subprocess.Popen(argv,stdout=log,stderr=log,pass_fds=(cr,aw),preexec_fn=limits,
                               env=dict(os.environ,DEBUGINFOD_URLS=''))
        os.close(cr);os.close(aw);status['profiler_pid']=child.pid
        try:
            os.write(cw,b'enable\n');ack=b''
            until=min(time.monotonic()+3,deadline/1e9)
            while b'ack\n' not in ack and time.monotonic()<until:
                if not select.select([ar],[],[],max(0,until-time.monotonic()))[0]:break
                chunk=os.read(ar,64)
                if not chunk:break
                ack+=chunk
            status['enable_ack_hex']=ack.hex()
            if b'ack\n' not in ack:raise RuntimeError('Enable acknowledgement absent')
            status['enabled_anchor']=anchor(pid,child.pid)
            deadline=min(deadline,status['enabled_anchor']['monotonic_ns']+25*10**9)
            dump(directory/'profile-ready.json',status)
            with (directory/'profile-clock.ndjson').open('x') as clocks:
                while child.poll() is None and time.monotonic_ns()<deadline:
                    row=anchor(pid,child.pid);clocks.write(json.dumps(row)+'\n');clocks.flush()
                    if stopped:reason='controller-stop';break
                    if row['target_stat'] is None:reason='target-exited';break
                    if int(row['target_stat'].rsplit(')',1)[1].split()[19])!=status['target_identity']['start_ticks']:
                        reason='target-identity-changed';break
                    if output.exists() and output.stat().st_size>=SOFT:reason='soft-size-limit';break
                    time.sleep(min(.05,max(0,(deadline-time.monotonic_ns())/1e9)))
                if child.poll() is not None:reason='perf-exited'
            status['disable_requested_anchor']=anchor(pid,child.pid)
            if child.poll() is None:
                os.write(cw,b'disable\n')
                if select.select([ar],[],[],.3)[0]:status['disable_ack_hex']=os.read(ar,64).hex()
            status['disabled_anchor']=anchor(pid,child.pid)
        except Exception as error:
            status['error']=str(error)
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:child.wait(timeout=1.5)
                except subprocess.TimeoutExpired:child.kill();child.wait();reason='forced-kill'
            os.close(cw);os.close(ar)
            u=resource.getrusage(resource.RUSAGE_CHILDREN);s=resource.getrusage(resource.RUSAGE_SELF)
            status.update(reason=reason,rc=child.returncode,ended_anchor=anchor(pid),elapsed_s=time.monotonic()-started,
                          profiler_cpu_s=u.ru_utime+u.ru_stime,profiler_maxrss_kib=u.ru_maxrss,
                          supervisor_cpu_s=s.ru_utime+s.ru_stime,supervisor_maxrss_kib=s.ru_maxrss,
                          file_bytes=output.stat().st_size if output.exists() else 0)
            dump(directory/'profile-status.json',status)

def supervise(directory, unit):
    d=pathlib.Path(directory);started=time.monotonic();stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    state={'armed_utc_ns':time.time_ns(),'profiles':{},'limits':{'active_seconds':50,'data_bytes':2*HARD}}
    dump(d/'profile-supervisor-ready.json',state)
    try:
        while not stopped and time.monotonic()-started<550:
            if (d/'guard-result.json').exists():break
            if (d/'phase.json').exists() and (d/'workload-start.json').exists():
                phase=json.loads((d/'phase.json').read_text())['phase2_utc_ns']
                pid=json.loads((d/'workload-start.json').read_text())['pid']
                if 'target_identity' not in state:
                    state['target_identity']=identity(pid)
                    if state['target_identity']['exe_sha256']!=EXPECTED:raise RuntimeError('Wrong bot executable')
                state['phase2_utc_ns']=phase
                for name,offset in (('early',0),('late',180)):
                    if name in state['profiles'] or time.time_ns()<phase+offset*10**9:continue
                    if identity(pid)!=state['target_identity']:raise RuntimeError('Bot identity changed')
                    # Mark before launching: no retry, even after a failed systemd call.
                    state['profiles'][name]={'dispatch_utc_ns':time.time_ns(),'offset_s':offset}
                    dump(d/'profile-supervisor-status.json',state)
                    argv=['systemd-run','--quiet','--unit='+unit+'-profile-'+name,
                          '--property=RuntimeMaxSec=30','--property=TimeoutStopSec=2',
                          '--property=KillMode=mixed','--property=MemoryMax=536870912',
                          '--property=LimitFSIZE='+str(HARD),'python3',str(pathlib.Path(__file__).resolve()),
                          'record','--directory',str(d/name),'--pid',str(pid),'--phase',str(phase),'--offset',str(offset)]
                    r=subprocess.run(argv,capture_output=True,text=True,timeout=4)
                    state['profiles'][name].update(argv=argv,rc=r.returncode,stderr=r.stderr)
                    dump(d/'profile-supervisor-status.json',state)
                if len(state['profiles'])==2:break
            time.sleep(.02 if 'phase2_utc_ns' not in state else .1)
    except Exception as error:state['error']=str(error)
    finally:
        u=resource.getrusage(resource.RUSAGE_SELF)
        state.update(ended_utc_ns=time.time_ns(),cpu_s=u.ru_utime+u.ru_stime,maxrss_kib=u.ru_maxrss)
        dump(d/'profile-supervisor-status.json',state)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('record','supervise'))
    p.add_argument('--directory',required=True);p.add_argument('--unit');p.add_argument('--pid',type=int)
    p.add_argument('--phase',type=int);p.add_argument('--offset',type=int,default=0);a=p.parse_args()
    if a.mode=='record':record(a.pid,a.directory,a.phase,a.offset)
    else:supervise(a.directory,a.unit)
