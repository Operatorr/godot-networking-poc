#!/usr/bin/env python3
"""Issue 39 exclusive zero-workload preservation; explicit one-shot stages only."""
import hashlib
import inspect
import json
import pathlib
import re
import shlex
import subprocess
import sys
import time

import clean_run
import clean_run_audit as audit
import clean_run_build as build
import clean_run_resources as resources
import closed_measurement_archive as archive
import native_diagnostic_r4 as r4
import native_diagnostic_storage as storage
import run

NS = 'clean-idle-maintenance-r1-20261024'
PREFIX = 'issue39-idle-measurement-maintenance-r1-20261024'
BASE = run.ROOT / 'deployment/hetzner/results' / PREFIX
REMOTE = '/home/deploy/omega-results/' + NS
UNIT = 'omega-' + NS
SELECTED = ['clean-strategy100-r1-20261024', NS]
MIRROR = '/home/deploy/omega-preservation-mirror/' + NS
GUARD = 8 * 1024**3
MARGIN = 32 * 1024**2


def save(name, value):
    with (BASE / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def ssh(role, command, label='commands'):
    return audit.bounded_ssh(role, command, BASE / (label + '.ndjson'))


def py(role, code, label='commands'):
    return json.loads(ssh(role, 'sudo -n python3 -c ' + shlex.quote(code), label))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def local_census():
    result = {}
    for root in (run.ROOT/'deployment/hetzner/results', run.ROOT/'docs/netcode/perf-notes'):
        for p in sorted(root.rglob('*')):
            if p.is_file() and BASE not in p.parents and not p.name.startswith(PREFIX):
                result[str(p.relative_to(run.ROOT))] = dict(bytes=p.stat().st_size, sha256=archive.digest(p))
    return result


COMMON = inspect.getsource(archive) + r'''
import subprocess,shutil,os,re,time
def command(args):return subprocess.check_output(args,text=True,timeout=8)
def snapshot(role,allow_recovery=False):
 result={}
 commands={
  'units':['systemctl','list-units','--all','--no-legend','omega-*'],
  'processes':['ps','-eo','pid,comm,args'],
  'queues':['ss','-u','-a','-m','-n','-p','-e'],
  'qdisc':['tc','-j','qdisc','show','dev','eth0'],
  'egress':['tc','-j','filter','show','dev','eth0','egress'],
  'ingress':['tc','-j','filter','show','dev','eth0','ingress'],
  'nft':['nft','list','ruleset'],
  'buffers':['sysctl','net.core.rmem_default','net.core.rmem_max','net.core.wmem_default','net.core.wmem_max'],
  'maintenance':['systemctl','show','apt-daily.timer','apt-daily-upgrade.timer','apt-daily.service','apt-daily-upgrade.service','-p','Id','-p','ActiveState','-p','UnitFileState'],
 }
 for k,c in commands.items():result[k]=command(c)
 assert not any(re.search(r'\sactive\s',line) and not (role=='game' and (line.strip().startswith('omega-loadtest-arena.service ') or (allow_recovery and line.strip().startswith('omega-clean-idle-maintenance-r1-20261024-restore.timer ')))) for line in result['units'].splitlines())
 bad=[]
 for line in result['processes'].splitlines()[1:]:
  parts=line.split(None,2)
  if len(parts)<3 or int(parts[0])==os.getpid() or parts[1] in ('bash','sh','sshd','sshd-session','sudo'):continue
  if parts[1] in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') or any(n in parts[2] for n in ('host_collect.py','capture.py','flow-record','udp_generator_profile')):bad.append(parts[0])
 assert not bad,bad
 assert 'omega-load-test' not in result['queues']
 assert all(int(v)==0 for pair in re.findall(r'UNCONN\s+(\d+)\s+(\d+)\s+.*omega-',result['queues']) for v in pair)
 assert not json.loads(result['ingress']) and not json.loads(result['egress'])
 result['free_bytes']=shutil.disk_usage('/home/deploy').free
 if role=='game':
  service='omega-loadtest-arena.service'
  result['unit']=command(['systemctl','cat',service])
  result['environment']=command(['systemctl','show',service,'-p','Environment','--value'])
  result['state']=command(['systemctl','show',service,'-p','ActiveState','-p','MainPID','-p','NRestarts','-p','ExecMainStartTimestampMonotonic'])
  result['config_sha256']=digest(pathlib.Path('/etc/omega-loadtest/arena.json'))
  result['measurement_conf_sha256']=digest(pathlib.Path('/etc/systemd/system/'+service+'.d/measurement.conf'))
  pid=command(['systemctl','show',service,'-p','MainPID','--value']).strip()
  result['exe_sha256']=digest(pathlib.Path('/proc')/pid/'exe')
  assert [line.split()[0] for line in result['processes'].splitlines()[1:] if len(line.split())>=2 and line.split()[1]=='omega-server']==[pid]
  result['metrics']=command(['curl','-fsS','--max-time','3','http://127.0.0.1:9100/metrics'])
  assert 'players_online 0' in result['metrics'].splitlines()
  assert 'ActiveState=active' in result['state'].splitlines()
  assert result['exe_sha256']=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2'
  assert result['config_sha256']=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c'
  assert 'OMEGA_MEASURE_DIR=/var/lib/omega-measure/current' in result['environment']
  assert all(x not in result['environment'] for x in ('OMEGA_AOI_AUDIT=','OMEGA_NATIVE_DIAG='))
  assert 'rb524288' in result['queues'] and 'tb524288' in result['queues']
  p=pathlib.Path('/var/lib/omega-measure/current');s=p.stat()
  assert p.resolve()==p and not p.is_symlink()
  result['current_directory']=dict(device=s.st_dev,inode=s.st_ino,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))
  result['current_allocated_bytes']=int(command(['du','-s','-B1',str(p)]).split()[0])
 else:
  assert not any(len(line.split())>=2 and line.split()[1]=='omega-server' for line in result['processes'].splitlines()[1:])
 result['closed_recoveries']={}
 for p in sorted(pathlib.Path('/home/deploy/omega-results').glob('clean-*/restore.sh')):
  for suffix in ('restore.timer','restore.service'):
   unit='omega-'+p.parent.name+'-'+suffix
   r=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True,timeout=3)
   assert r.stdout.strip() in ('inactive','unknown','failed') or (allow_recovery and unit=='omega-clean-idle-maintenance-r1-20261024-restore.timer' and r.stdout.strip()=='active'),(unit,r.stdout)
   result['closed_recoveries'][unit]=r.stdout.strip()
 return result
def protected():
 root=pathlib.Path('/home/deploy/omega-results')
 paths=set(root.glob('*/*.tar.gz'))|set(root.glob('*/*sha256*'))
 paths.update(root.glob('clean-*/restore.sh'))
 for old in root.glob('*/original'):
  paths.update(p for p in old.rglob('*') if p.is_file())
 for old in ('campaign-20261013','one-pass-20261014'):
  paths.update((root/old).glob('*state*.json'))
 paths.update(p for p in pathlib.Path('/home/deploy').glob('omega-*/rust/target/release/omega-*') if p.is_file() and not p.name.endswith('.d'))
 result={}
 for p in sorted(paths):
  assert not p.is_symlink() and p.resolve()==p
  s=p.stat();result[str(p)]=dict(sha256=digest(p),bytes=s.st_size,device=s.st_dev,inode=s.st_ino,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))
 return result
'''


def initialize():
    BASE.mkdir(exist_ok=False)
    # This script existed when the census was taken; its executed copy is retained.
    save('historical-local-before.json', local_census())
    (BASE/'executed.py').write_bytes(pathlib.Path(__file__).read_bytes())
    for role in ('game','bots'):
        result=py(role,COMMON+'\nprint(json.dumps(dict(snapshot=snapshot('+repr(role)+'),protected=protected())))')
        save(role+'-before.json',result)
        print(role+' fresh idle/exclusive snapshot saved; free='+str(result['snapshot']['free_bytes']),flush=True)


def guarded_script(remote):
    return '#!/bin/sh\nset -eu\nexec flock -w 20 '+shlex.quote(remote+'/recovery.lock')+' /bin/sh '+shlex.quote(remote+'/restore.sh')+' "${1:-restore}"\n'


def rotate():
    clean_run.REMOTE=REMOTE
    clean_run.OVERRIDE='/run/systemd/system/'+clean_run.SERVICE+'.d/zz-'+NS+'.conf'
    clean_run.CELL={'measurement_preservation':'rename-v1'}
    script=clean_run.recovery_script()
    (BASE/'restore.sh').write_text(script)
    # Shared recovery code runs behind flock for both the primary and timer paths.
    wrapper=guarded_script(REMOTE)
    (BASE/'guarded-restore.sh').write_text(wrapper)
    code=COMMON+'\n'+f'''
snapshot('game')
remote=pathlib.Path({REMOTE!r});assert not remote.exists()
assert not pathlib.Path({clean_run.OVERRIDE!r}).exists()
remote.mkdir();(remote/'original').mkdir()
assert remote.stat().st_dev==pathlib.Path('/var/lib/omega-measure/current').stat().st_dev
(remote/'restore.sh').write_text({script!r})
(remote/'guarded-restore.sh').write_text({wrapper!r})
os.chown(remote,1000,1000);os.chown(remote/'original',1000,1000)
for p in (remote/'restore.sh',remote/'guarded-restore.sh'):os.chmod(p,0o755);os.chown(p,1000,1000)
command(['systemd-run','--unit={UNIT}-restore','--on-active=120s','--timer-property=AccuracySec=1s','--property=Type=oneshot','--property=TimeoutStartSec=75s','/bin/sh',str(remote/'guarded-restore.sh')])
assert command(['systemctl','is-active','{UNIT}-restore.timer']).strip()=='active'
print(json.dumps(dict(armed=True,recovery_sha256=digest(remote/'restore.sh'),timer=command(['systemctl','show','{UNIT}-restore.timer','-p','ActiveState','-p','NextElapseUSecMonotonic']))))
'''
    save('recovery-armed.json',py('game',code))
    # One restore call performs stop, frozen manifest, atomic rename, recreation,
    # pinned original restart and two exact stable PID/hash observations.
    output=ssh('game','sudo -n timeout 70s /bin/sh '+shlex.quote(REMOTE+'/guarded-restore.sh')+' restore')
    save('restoration-output.json',dict(stdout=output))
    finish_rotation()


def finish_rotation():
    # Never disarm unless independent ready/idle checks succeed twice and unchanged.
    checks=[]
    for _ in range(2):
        checks.append(py('game',COMMON+'\nprint(json.dumps(snapshot("game",allow_recovery=True)))'))
    assert checks[0]['state']==checks[1]['state']
    before=json.loads((BASE/'game-before.json').read_text())['snapshot']
    for result in checks:
        for key in ('unit','environment','config_sha256','measurement_conf_sha256','buffers','maintenance'):
            assert result[key]==before[key],key
        assert result['current_directory']['inode']!=before['current_directory']['inode']
        assert {k:v for k,v in result['current_directory'].items() if k!='inode'}=={k:v for k,v in before['current_directory'].items() if k!='inode'}
    save('restored-twice.json',checks)
    save('recovery-disarmed.json',py('game',f'''
import subprocess,json
subprocess.run(['systemctl','stop','{UNIT}-restore.timer'],check=True,timeout=5)
r=subprocess.run(['systemctl','is-active','{UNIT}-restore.service'],capture_output=True,text=True,timeout=5)
assert r.stdout.strip() in ('inactive','unknown'),r.stdout
print(json.dumps(dict(timer=subprocess.run(['systemctl','is-active','{UNIT}-restore.timer'],capture_output=True,text=True).stdout.strip(),recovery_service=r.stdout.strip())))
'''))
    save('post-rotation.json',py('game',COMMON+'\nprint(json.dumps(dict(snapshot=snapshot("game"),rows={ns:dict(inventory=inventory(pathlib.Path("/home/deploy/omega-results")/ns/"original/measurement-current"),manifest=(pathlib.Path("/home/deploy/omega-results")/ns/"original/measurement-sha256.txt").read_text(),verified=verify(pathlib.Path("/home/deploy/omega-results")/ns/"original")) for ns in '+repr(SELECTED)+'})))'))
    print('Guarded original rotation restored, verified twice, recovery disarmed',flush=True)


def transfer(role, command, source=None, destination=None):
    """Bounded binary stream; private journal records command, result and exact bytes."""
    assert (source is None)!=(destination is None)
    host=run.HOSTS[role]
    argv=['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,host['ssh_user']+'@'+host['ipv4'],command]
    row=dict(utc_ns=time.time_ns(),role=role,command=command,timeout_s=90)
    try:
        if source:
            with source.open('rb') as stream:
                result=subprocess.run(argv,stdin=stream,capture_output=True,timeout=90)
            row.update(input_bytes=source.stat().st_size,input_sha256=archive.digest(source),stdout=result.stdout.decode(errors='replace'))
        else:
            with destination.open('xb') as stream:
                result=subprocess.run(argv,stdout=stream,stderr=subprocess.PIPE,timeout=90)
            row.update(output_bytes=destination.stat().st_size,output_sha256=archive.digest(destination))
        row.update(returncode=result.returncode,stderr=result.stderr.decode(errors='replace'))
    except subprocess.TimeoutExpired:
        row['timeout']=True
        raise RuntimeError('Bounded preservation stream timed out; retain partial evidence') from None
    finally:
        with (BASE/'commands.ndjson').open('a') as stream:stream.write(json.dumps(row)+'\n')
    assert result.returncode==0,'Preservation stream failed; private journal retained'


def upload(role, source, destination):
    sha=archive.digest(source)
    command='set -eu; test ! -e '+shlex.quote(destination)+'; test ! -e '+shlex.quote(destination+'.partial')+'; cat > '+shlex.quote(destination+'.partial')+'; test "$(sha256sum '+shlex.quote(destination+'.partial')+' | cut -d " " -f1)" = '+shlex.quote(sha)+'; mv '+shlex.quote(destination+'.partial')+' '+shlex.quote(destination)
    transfer(role,command,source=source)


def archive_local():
    rows=json.loads((BASE/'post-rotation.json').read_text())['rows']
    proofs={}
    for ns in SELECTED:
        original=BASE/ns/'original';original.mkdir(parents=True,exist_ok=False)
        remote='/home/deploy/omega-results/'+ns+'/original'
        # Fetch exact external frozen files; do not synthesize preservation markers.
        for filename in ('measurement-sha256.txt','measurement-verified','arena.json','measurement.conf'):
            transfer('game','sudo -n cat '+shlex.quote(remote+'/'+filename),destination=original/filename)
        assert (original/'measurement-sha256.txt').read_text()==rows[ns]['manifest']
        assert (original/'measurement-verified').read_bytes()==b''
        before=py('game',COMMON+'\nns='+repr(ns)+'\np=pathlib.Path("/home/deploy/omega-results")/ns/"original"\nsnapshot("game")\nprint(json.dumps(dict(inventory=inventory(p/"measurement-current"),restore_sha256=digest(p.parent/"restore.sh"),verified=verify(p))))')
        assert before['inventory']==rows[ns]['inventory']
        transfer('game','sudo -n tar -czf - -C '+shlex.quote(remote)+' measurement-current',destination=original/archive.ARCHIVE)
        proof=dict(schema=archive.SCHEMA,namespace=ns,inventory=before['inventory'],archive_bytes=(original/archive.ARCHIVE).stat().st_size,
                   archive_sha256=archive.digest(original/archive.ARCHIVE),manifest_sha256=archive.digest(original/'measurement-sha256.txt'),
                   closed_unit_states={k:v for k,v in json.loads((BASE/'post-rotation.json').read_text())['snapshot']['closed_recoveries'].items() if ns in k},
                   frozen_recovery_sha256=before['restore_sha256'])
        (original/archive.PROOF).write_text(json.dumps(proof,indent=2)+'\n')
        proofs[ns]=dict(proof=proof,verified=archive.verify(original),files={p.name:dict(bytes=p.stat().st_size,sha256=archive.digest(p)) for p in sorted(original.iterdir())})
    save('local-complete-proof.json',proofs)
    print('Both closed backups streamed and independently verified locally',flush=True)


def mirror():
    local=json.loads((BASE/'local-complete-proof.json').read_text())
    needed=sum(((v['bytes']+4095)//4096)*4096 for row in local.values() for v in row['files'].values())+16*4096
    code=COMMON+'\n'+f'''
s=snapshot('bots');assert s['free_bytes']>={GUARD+MARGIN+needed}
root=pathlib.Path({MIRROR!r});assert not root.exists()
for ns in {SELECTED!r}:
 p=root/ns/'original';p.mkdir(parents=True);os.chown(p,1000,1000)
print(json.dumps(dict(free_bytes=s['free_bytes'],required_mirror_allocated_upper_bound={needed},reserve_bytes={GUARD},margin_bytes={MARGIN})))
'''
    save('mirror-allowance.json',py('bots',code))
    for ns in SELECTED:
        for p in sorted((BASE/ns/'original').iterdir()):upload('bots',p,MIRROR+'/'+ns+'/original/'+p.name)
    result=py('bots',COMMON+'\nroot=pathlib.Path('+repr(MIRROR)+')\nsnapshot("bots")\nprint(json.dumps({ns:dict(verified=verify(root/ns/"original"),files={p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted((root/ns/"original").iterdir())}) for ns in '+repr(SELECTED)+'}))')
    for ns in SELECTED:
        assert result[ns]['verified']==local[ns]['verified'] and result[ns]['files']==local[ns]['files']
    save('mirror-complete-proof.json',result)
    print('Independent bot preservation mirror verified every member and metadata',flush=True)


def reclaim():
    local=json.loads((BASE/'local-complete-proof.json').read_text())
    mirror=json.loads((BASE/'mirror-complete-proof.json').read_text())
    for ns in SELECTED:
        assert archive.verify(BASE/ns/'original')==local[ns]['verified']
        assert all(archive.digest(BASE/ns/'original'/name)==row['sha256'] for name,row in local[ns]['files'].items())
    fresh=py('bots',COMMON+'\nroot=pathlib.Path('+repr(MIRROR)+')\nsnapshot("bots")\nprint(json.dumps({ns:dict(verified=verify(root/ns/"original"),files={p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted((root/ns/"original").iterdir())}) for ns in '+repr(SELECTED)+'}))')
    assert fresh==mirror
    save('pre-reclaim-mirror-recheck.json',fresh)
    # Durable transition journal exists on game before removing any closed raw tree.
    transition=dict(schema='two-offhost-preservation-transition-v1',workloads=0,local=str(BASE),mirror=MIRROR,
                    local_proof_sha256=archive.digest(BASE/'local-complete-proof.json'),mirror_proof_sha256=archive.digest(BASE/'mirror-complete-proof.json'),
                    archives={ns:local[ns]['proof'] for ns in SELECTED},phase='two-independent-offhost-copies-verified')
    save('transition-plan.json',transition)
    code=COMMON+'\n'+f'''
plan={transition!r}
snapshot('game')
root=pathlib.Path('/home/deploy/omega-results')
journal=pathlib.Path({REMOTE!r})/'preservation-transition.ndjson'
assert not journal.exists()
def record(row):
 with journal.open('a') as stream:
  stream.write(json.dumps(dict(utc_ns=time.time_ns(),**row))+'\\n');stream.flush();os.fsync(stream.fileno())
for ns,proof in plan['archives'].items():
 p=root/ns/'original'
 assert inventory(p/'measurement-current')==proof['inventory']
 assert digest(p/'measurement-sha256.txt')==proof['manifest_sha256']
 assert digest(p.parent/'restore.sh')==proof['frozen_recovery_sha256']
 assert verify(p)['mode']=='loose'
 assert not (p/ARCHIVE).exists() and not (p/PROOF).exists()
record(plan)
before=shutil.disk_usage(root).free
allocated={{}}
for ns,proof in plan['archives'].items():
 p=root/ns/'original/measurement-current'
 assert p.resolve()==p and not p.is_symlink() and p.parent.parent.parent==root
 assert inventory(p)==proof['inventory']
 allocated[ns]=int(command(['du','-s','-B1',str(p)]).split()[0])
 record(dict(phase='delete-exact-closed-raw-begin',namespace=ns,inventory=proof['inventory']))
 shutil.rmtree(p)
 record(dict(phase='closed-raw-removed-install-pending',namespace=ns))
print(json.dumps(dict(free_before=before,free_after=shutil.disk_usage(root).free,raw_allocated_bytes=allocated,transition_sha256=digest(journal))))
'''
    save('reclaim-result.json',py('game',code))
    print('Only the two exact closed raw trees reclaimed after two verified off-game copies',flush=True)


def install_game():
    local=json.loads((BASE/'local-complete-proof.json').read_text())
    needed=sum(((local[ns]['files'][name]['bytes']+4095)//4096)*4096 for ns in SELECTED for name in (archive.ARCHIVE,archive.PROOF))
    save('game-archive-upload-allowance.json',py('game',COMMON+'\ns=snapshot("game")\nassert s["free_bytes"]>='+repr(GUARD+MARGIN+needed)+'\nprint(json.dumps(dict(free_bytes=s["free_bytes"],archive_and_proof_allocated_upper_bound='+repr(needed)+',reserve_bytes='+repr(GUARD)+',margin_bytes='+repr(MARGIN)+')))'))
    for ns in SELECTED:
        for name in (archive.ARCHIVE,archive.PROOF):
            upload('game',BASE/ns/'original'/name,'/home/deploy/omega-results/'+ns+'/original/'+name)
    result=py('game',COMMON+'\nroot=pathlib.Path("/home/deploy/omega-results")\nresults={ns:verify(root/ns/"original") for ns in '+repr(SELECTED)+'}\np=root/'+repr(NS)+'/"preservation-transition.ndjson"\nwith p.open("a") as stream:stream.write(json.dumps(dict(utc_ns=time.time_ns(),phase="game-archive-installed-verified",results=results))+"\\n");stream.flush();os.fsync(stream.fileno())\nprint(json.dumps(dict(results=results,snapshot=snapshot("game"),transition_sha256=digest(p))))')
    for ns in SELECTED:assert result['results'][ns]==local[ns]['verified']
    save('game-installed-proof.json',result)
    transfer('game','sudo -n cat '+shlex.quote(REMOTE+'/preservation-transition.ndjson'),destination=BASE/'preservation-transition.ndjson')
    print('Identical game archives installed and unchanged archive verifier passed',flush=True)


def release(label):
    assert re.fullmatch(r'release-[a-z]',label)
    assert not (BASE/(label+'.ndjson')).exists(), 'Use a fresh audit label'
    local=json.loads((BASE/'local-complete-proof.json').read_text())
    all_proofs={p.parent.name.removesuffix('-build'):json.loads(p.read_text()) for p in BASE.parent.glob('clean-*-build/build-proof.json')}
    result={}
    for role in ('game','bots'):
        before=json.loads((BASE/(role+'-before.json')).read_text())
        current=py(role,COMMON+'\nprint(json.dumps(dict(snapshot=snapshot('+repr(role)+'),protected=protected())))',label)
        baseline=before['snapshot'];now=current['snapshot']
        for key in ('qdisc','buffers','maintenance'):
            assert now[key]==baseline[key],key
        strip=lambda s:re.sub(r'counter packets \d+ bytes \d+','counter',s)
        assert strip(now['nft'])==strip(baseline['nft'])
        if role=='game':
            for key in ('unit','environment','config_sha256','measurement_conf_sha256'):
                assert now[key]==baseline[key],key
            restored=json.loads((BASE/'restored-twice.json').read_text())[-1]
            assert now['state']==restored['state'],'Unexpected original restart or PID change'
            assert now['current_directory']==restored['current_directory']
        removed={str(pathlib.PurePosixPath('/home/deploy/omega-results')/SELECTED[0]/'original/measurement-current'/name) for name in local[SELECTED[0]]['proof']['inventory']['files']} if role=='game' else set()
        assert all(current['protected'].get(k)==v for k,v in before['protected'].items() if k not in removed),'Prior protected evidence changed'
        assert all(k not in current['protected'] for k in removed)
        candidates={n:{k:p[role][k] for k in ('revision','path','sha256','bot_sha256')} for n,p in all_proofs.items()}
        code=inspect.getsource(resources)+'\nimport json\nprint(json.dumps({n:candidate(r) for n,r in '+repr(candidates)+'.items()}))'
        candidate_results=py(role,code,label)
        sparse_codes={n:shlex.split(build.sparse_source_proof_command(p[role]['path'],p[role]['revision']))[2] for n,p in all_proofs.items() if p[role].get('checkout_mode')=='rust-only-cone'}
        # Each child read is bounded too; one SSH invocation has the usual 90 s cap.
        code='import subprocess,json\ncodes='+repr(sparse_codes)+'\nprint(json.dumps({n:json.loads(subprocess.check_output(["python3","-c",code],text=True,timeout=10)) for n,code in codes.items()}))'
        sparse_results=py(role,code,label)
        # All original/candidate/control/old/baseline executable hashes are already
        # compared with the before census. Verify ELF and dynamic links additionally.
        paths=[p for p in current['protected'] if '/rust/target/release/omega-' in p]
        elf=json.loads(ssh(role,r4.elf_identity_command(paths,native_cargo_artifact=True),label))
        dependencies=py(role,'import subprocess,json\npaths='+repr(paths)+'\nresult={p:subprocess.check_output(["ldd",p],text=True,timeout=5) for p in paths}\nassert all("not found" not in v for v in result.values())\nprint(json.dumps(result))',label)
        if role=='game':
            backups=json.loads(ssh(role,audit.measurement_backups_command(),label))
            assert len(backups)==19 and all(v['mode']==archive.SCHEMA for v in backups.values())
            for ns in SELECTED:assert backups[ns]==local[ns]['verified']
            copies=py(role,COMMON+'\nroot=pathlib.Path("/home/deploy/omega-results")\nprint(json.dumps({ns:{p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted((root/ns/"original").iterdir())} for ns in '+repr(SELECTED)+'}))',label)
            for ns in SELECTED:
                assert {name:copies[ns][name] for name in local[ns]['files']}==local[ns]['files']
        else:
            backups=None
            copies=py(role,COMMON+'\nroot=pathlib.Path('+repr(MIRROR)+')\nprint(json.dumps({ns:dict(verified=verify(root/ns/"original"),files={p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted((root/ns/"original").iterdir())}) for ns in '+repr(SELECTED)+'}))',label)
            for ns in SELECTED:assert copies[ns]['verified']==local[ns]['verified'] and copies[ns]['files']==local[ns]['files']
        save(role+'-'+label+'-raw.json',dict(current=current,candidates=candidate_results,sparse=sparse_results,elf=elf,dependencies=dependencies,backups=backups,copies=copies))
        result[role]=dict(checks_pass=True,prior_protected_files_unchanged=len(before['protected'])-len(removed),explicit_closed_raw_files_replaced=len(removed),
                          source_proofs=len(candidate_results),sparse_materialized_byte_proofs=len(sparse_results),executable_elf_and_dependency_proofs=len(elf),
                          free_bytes=now['free_bytes'],archived_backup_count=len(backups) if backups else None,
                          raw_sha256=archive.digest(BASE/(role+'-'+label+'-raw.json')))
    # Fresh local verification is independent of both remote verifiers.
    for ns in SELECTED:
        assert archive.verify(BASE/ns/'original')==local[ns]['verified']
        assert all(archive.digest(BASE/ns/'original'/name)==row['sha256'] for name,row in local[ns]['files'].items())
    save(label+'-summary.json',dict(label=label,checks_pass=True,hosts=result,workloads=0,command_timeout_s=90,
                                  command_count=len((BASE/(label+'.ndjson')).read_text().splitlines()),commands_sha256=archive.digest(BASE/(label+'.ndjson'))))
    print(label+' full release/preservation audit passed on both hosts',flush=True)


def final():
    old=json.loads((BASE/'historical-local-before.json').read_text())
    current=local_census()
    assert all(current.get(k)==v for k,v in old.items()),'Historical local evidence changed'
    save('historical-local-after-proof.json',dict(files=len(old),all_prior_files_unchanged=True,census_sha256=fingerprint(old)))
    # Measure a local Git transport bundle ONLY to price a future exact same-source
    # verified-copy stage. This is not uploaded or materialized on either host.
    bundle=BASE/'future-allowance-only.bundle'
    subprocess.run(['git','bundle','create',str(bundle),build.BASE_REVISION+'..HEAD'],check=True,capture_output=True,timeout=90)
    subprocess.run(['git','bundle','verify',str(bundle)],check=True,capture_output=True,timeout=30)
    proof=json.loads((BASE.parent/'clean-strategy100-r1-20261024-build/build-proof.json').read_text())
    binary_bytes=sum(proof['game']['binary_bytes'].values())
    staging=storage.sparse_checkout_allowance(r4.REVISION,bundle.stat().st_size,binary_bytes)
    budget=r4.budget(json.loads(ssh('game',r4.rename_probe_command(staging),'final')))
    budget.update(actual_profile='native-r4 ordinary Strategy100, unchanged full allowances',local_only_bundle_bytes=bundle.stat().st_size,
                  local_only_bundle_sha256=archive.digest(bundle),bundle_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  pinned_runtime_source=r4.REVISION,binary_pair_bytes=binary_bytes,no_remote_staging=True)
    save('future-strategy100-allowance.json',budget)
    snapshots={role:py(role,COMMON+'\nprint(json.dumps(snapshot('+repr(role)+')))','final') for role in ('game','bots')}
    save('final-host-snapshots.json',snapshots)
    reclaim=json.loads((BASE/'reclaim-result.json').read_text())
    installed=json.loads((BASE/'game-installed-proof.json').read_text())
    proofs=json.loads((BASE/'local-complete-proof.json').read_text())
    summary=dict(namespace=NS,workloads=0,bots=0,load_experiments=0,hosts_released=True,
                 restored_original_service=True,recovery_timer_inactive=True,unchanged_guard_bytes=GUARD,
                 new_archived_originals=SELECTED,archived_backup_count=19,loose_backup_count=0,
                 raw_logical_bytes=sum(v['verified']['bytes'] for v in proofs.values()),raw_allocated_bytes=sum(reclaim['raw_allocated_bytes'].values()),
                 raw_removal_observed_gain=reclaim['free_after']-reclaim['free_before'],
                 archive_bytes=sum(v['proof']['archive_bytes'] for v in proofs.values()),
                 archive_and_proof_allocation_bound=json.loads((BASE/'game-archive-upload-allowance.json').read_text())['archive_and_proof_allocated_upper_bound'],
                 free_before=json.loads((BASE/'game-before.json').read_text())['snapshot']['free_bytes'],
                 free_after_install=installed['snapshot']['free_bytes'],current_free={role:s['free_bytes'] for role,s in snapshots.items()},
                 future_full_allowance=budget,mirror=MIRROR,local=str(BASE),
                 local_historical_files_unchanged=len(old),audits={label:json.loads((BASE/(label+'-summary.json')).read_text()) for label in ('release-b','release-c')},
                 archive_identities={ns:dict(archive_sha256=row['proof']['archive_sha256'],archive_bytes=row['proof']['archive_bytes'],
                       proof_sha256=archive.digest(BASE/ns/'original'/archive.PROOF),manifest_sha256=row['proof']['manifest_sha256']) for ns,row in proofs.items()},
                 limitations=['Idle recorder continues growing; allowance is a point-in-time measurement.','Original archived inode/device values are historical metadata, not live loose inodes.','Old recovery scripts remain frozen and cannot run until loose trees are restored.','No runtime gates or workload classifications were evaluated.'])
    summary['observed_net_game_free_change']=summary['current_free']['game']-summary['free_before']
    save('summary.json',summary)
    print(json.dumps(dict(workloads=0,hosts_released=True,current_free=summary['current_free'],future_allowance_passed=budget['passed'],remaining_bytes=budget['remaining_above_guard_after_allowance'])),flush=True)


if __name__=='__main__':
    if BASE.exists():
        source=pathlib.Path(__file__).read_bytes()
        recorded=BASE/('controller-'+sys.argv[1]+'-'+hashlib.sha256(source).hexdigest()+'.py')
        if not recorded.exists():recorded.write_bytes(source)
    if re.fullmatch(r'release-[a-z]',sys.argv[1]):release(sys.argv[1])
    else:{'initialize':initialize,'rotate':rotate,'finish-rotation':finish_rotation,'archive-local':archive_local,'mirror':mirror,'reclaim':reclaim,'install-game':install_game,'final':final}[sys.argv[1]]()
