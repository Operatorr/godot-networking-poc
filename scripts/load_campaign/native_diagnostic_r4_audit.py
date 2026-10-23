#!/usr/bin/env python3
"""Two exact R4 read-only release audits; never launches or restores a workload."""
import hashlib
import inspect
import json
import pathlib
import shlex
import sys
import time
import clean_run_audit as audit
import clean_run_build as build
import clean_run_resources as resources
import native_diagnostic_r4 as r3
import run

ORIGINALS_CODE='''import pathlib,hashlib,json,stat
result={}
for p in pathlib.Path('/home/deploy/omega-results').glob('*/original'):
 assert p.is_dir() and not p.is_symlink() and p.resolve()==p
 for f in p.rglob('*'):
  assert not f.is_symlink(),str(f)
  if f.is_file():
   s=f.stat();result[str(f)]=dict(sha256=hashlib.file_digest(f.open('rb'),'sha256').hexdigest(),bytes=s.st_size,inode=s.st_ino,device=s.st_dev,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))
print(json.dumps(result))
'''


def freeze_originals():
    r3.connection_options()
    directory=run.ROOT/'deployment/hetzner/results'/(r3.NAMESPACE+'-build')
    for role in ('game','bots'):
        output=directory/(role+'-originals-before.json')
        if output.exists():raise FileExistsError('Original backup census already frozen')
        raw=audit.bounded_ssh(role,'sudo -n python3 -c '+shlex.quote(ORIGINALS_CODE),directory/'originals-before-commands.ndjson')
        with output.open('x') as stream:stream.write(raw)
    print('Both full original-backup file censuses frozen; no workload launched',flush=True)


def main():
    r3.connection_options()
    ns=r3.NAMESPACE;p=run.ROOT/'deployment/hetzner/results'/ns;pre=p.with_name(ns+'-preflight');b=p.with_name(ns+'-build')
    assert (p/'cleanup.json').exists()
    proofs={f.parent.name.removesuffix('-build'):json.loads(f.read_text()) for f in p.parent.glob('clean-*-build/build-proof.json')}
    for preservation,restoration,label in (('independent','final','r4-release-a'),('r4-independent-recheck','r4-final-recheck','r4-release-b')):
        started=time.time_ns();sys.argv=['audit','--namespace',ns,'--verification-label',preservation,'--restoration-label',restoration]
        result=audit.main();journal=p/(preservation+'-audit-commands.ndjson');extra={}
        for role in ('game','bots'):
            rows={n:{k:v[role][k] for k in ('revision','path','sha256','bot_sha256')} for n,v in proofs.items()}
            code='import hashlib,pathlib,shutil,subprocess,json\nINTERMEDIATES='+repr(resources.INTERMEDIATES)+'\n'+inspect.getsource(resources.candidate)
            code+='\nprint(json.dumps({n:candidate(r) for n,r in '+repr(rows)+'.items()}))'
            candidates=json.loads(audit.bounded_ssh(role,'python3 -c '+shlex.quote(code),journal))
            sparse=json.loads(audit.bounded_ssh(role,build.sparse_source_proof_command('/home/deploy/omega-'+ns,r3.REVISION),journal))
            originals=json.loads(audit.bounded_ssh(role,'sudo -n python3 -c '+shlex.quote(ORIGINALS_CODE),journal))
            previous=json.loads((b/(role+'-originals-before.json')).read_text())
            assert all(originals.get(k)==v for k,v in previous.items()),'Historical original backup damaged'
            backup='/home/deploy/omega-results/'+ns+'/original/'
            if role=='game':
                assert originals[backup+'measurement-sha256.txt']['sha256']==hashlib.sha256((p/'preserved-measurement-sha256.txt').read_bytes()).hexdigest()
                assert originals[backup+'measurement-verified']['sha256']==hashlib.sha256(b'').hexdigest()
                restore_sha=audit.bounded_ssh(role,'sha256sum /home/deploy/omega-results/'+ns+'/restore.sh',journal).split()[0]
                assert restore_sha==hashlib.sha256((p/'restore.sh').read_bytes()).hexdigest()
            baseline=json.loads((b/(role+'-before.json')).read_text())
            raw={k:audit.bounded_ssh(role,c,journal) for k,c in dict(
                maintenance='systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
                buffers='sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max').items()}
            assert raw['maintenance']==baseline['maintenance'] and raw['buffers']==baseline['buffers']
            if role=='game':
                proof=json.loads((b/'storage-before-staging.json').read_text())['measurement']['measurement']
                code='''import pathlib,os,stat,json,hashlib
old=PROOF
p=pathlib.Path(BACKUP);s=p.stat();current=pathlib.Path('/var/lib/omega-measure/current');t=current.stat()
assert p.resolve()==p and current.resolve()==current and not p.is_symlink() and not current.is_symlink()
assert (s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(old['device'],old['inode'],old['uid'],old['gid'],old['mode'])
assert (t.st_uid,t.st_gid,stat.S_IMODE(t.st_mode))==(old['uid'],old['gid'],old['mode']) and t.st_ino!=s.st_ino
prefix={}
for name,row in old['files'].items():
 f=p/name;v=f.stat()
 with f.open('rb') as stream:digest=hashlib.sha256(stream.read(row['bytes'])).hexdigest()
 assert (v.st_ino,v.st_dev)==(row['inode'],row['device']) and digest==row['sha256']
 prefix[name]=dict(before_bytes=row['bytes'],preserved_bytes=v.st_size,prefix_sha256=digest,inode=v.st_ino)
print(json.dumps(dict(same_filesystem_atomic_rename_proven=True,original_inodes_preserved=True,recreated_owner_mode=True,prefix=prefix)))
'''.replace('PROOF',repr(proof)).replace('BACKUP',repr('/home/deploy/omega-results/'+ns+'/original/measurement-current'))
                raw['rename']=json.loads(audit.bounded_ssh(role,'sudo -n python3 -c '+shlex.quote(code),journal))
                env=audit.bounded_ssh(role,'systemctl show omega-loadtest-arena.service -p Environment --value',journal)
                assert 'OMEGA_NATIVE_DIAG=' not in env and 'OMEGA_AOI_AUDIT=' not in env
            extra[role]=dict(all_candidates=candidates,sparse=sparse,prior_original_file_count=len(previous),all_prior_original_files_unchanged=True,
                frozen_current_backup_manifest_and_marker_verified=True if role=='game' else None,
                frozen_recovery_sha256=restore_sha if role=='game' else None,raw=raw)
        summary=dict(label=label,started_utc_ns=started,ended_utc_ns=time.time_ns(),checks_pass=all(all(v['checks'].values()) for v in result.values()),
            restoration_label=restoration,preservation_label=preservation,bounded_command_count=len(journal.read_text().splitlines()),command_timeout_s=90,
            commands_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),extra=extra)
        with (pre/(label+'-composite-audit.json')).open('x') as stream:json.dump(summary,stream,indent=2)
        assert summary['checks_pass'];print(json.dumps(dict(label=label,passed=True,bounded_command_count=summary['bounded_command_count'])),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['freeze-originals']:freeze_originals()
    elif not sys.argv[1:]:main()
    else:raise ValueError('Only explicit original census or the two release audits')
