#!/usr/bin/env python3
"""Exact diagnostic/ordinary read-only release audits after automatic restoration."""
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


def freeze_originals(namespace=r3.NAMESPACE):
    if namespace not in r3.NAMESPACES:raise ValueError("Only exact R4/R5 namespaces")
    r3.connection_options()
    directory=run.ROOT/'deployment/hetzner/results'/(namespace+'-build')
    for role in ('game','bots'):
        output=directory/(role+'-originals-before.json')
        if output.exists():raise FileExistsError('Original backup census already frozen')
        raw=audit.bounded_ssh(role,'sudo -n python3 -c '+shlex.quote(ORIGINALS_CODE),directory/'originals-before-commands.ndjson')
        with output.open('x') as stream:stream.write(raw)
    print('Both full original-backup file censuses frozen; no workload launched',flush=True)


def main(namespace=r3.NAMESPACE):
    if namespace not in r3.NAMESPACES:raise ValueError("Only exact R4/R5 namespaces")
    r3.connection_options()
    ns=namespace;p=run.ROOT/'deployment/hetzner/results'/ns;pre=p.with_name(ns+'-preflight');b=p.with_name(ns+'-build')
    assert (p/'cleanup.json').exists()
    proofs={f.parent.name.removesuffix('-build'):json.loads(f.read_text()) for f in p.parent.glob('clean-*-build/build-proof.json')}
    round_name=r3.ROUND_NAMES[ns]
    for preservation,restoration,label in (('independent','final',round_name+'-release-a'),(round_name+'-independent-recheck',round_name+'-final-recheck',round_name+'-release-b')):
        started=time.time_ns();sys.argv=['audit','--namespace',ns,'--verification-label',preservation,'--restoration-label',restoration]
        result=audit.main();journal=p/(preservation+'-audit-commands.ndjson');extra={}
        for role in ('game','bots'):
            rows={n:{k:v[role][k] for k in ('revision','path','sha256','bot_sha256')} for n,v in proofs.items()}
            code='import hashlib,pathlib,shutil,subprocess,json\nINTERMEDIATES='+repr(resources.INTERMEDIATES)+'\n'+inspect.getsource(resources.candidate)
            code+='\nprint(json.dumps({n:candidate(r) for n,r in '+repr(rows)+'.items()}))'
            candidates=json.loads(audit.bounded_ssh(role,'python3 -c '+shlex.quote(code),journal))
            sparse={name:json.loads(audit.bounded_ssh(role,build.sparse_source_proof_command(proof[role]['path'],proof[role]['revision']),journal))
                    for name,proof in proofs.items() if proof[role].get('checkout_mode')=='rust-only-cone'}
            elf=json.loads(audit.bounded_ssh(role,r3.elf_identity_command([proofs[ns][role]['path']+'/rust/target/release/'+n for n in ('omega-server','omega-load-test')]),journal))
            recoveries={}
            for old in sorted(p.parent.glob('clean-*/restore.sh')):
                remote='/home/deploy/omega-results/'+old.parent.name+'/restore.sh'
                digest=audit.bounded_ssh(role,'if test -f '+remote+'; then sha256sum '+remote+'; else echo absent; fi',journal).split()[0]
                if role=='game':assert digest==hashlib.sha256(old.read_bytes()).hexdigest(),remote
                recoveries[old.parent.name]=digest
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
            extra[role]=dict(all_candidates=candidates,sparse=sparse,elf=elf,frozen_recoveries=recoveries,prior_original_file_count=len(previous),all_prior_original_files_unchanged=True,
                frozen_current_backup_manifest_and_marker_verified=True if role=='game' else None,
                frozen_recovery_sha256=restore_sha if role=='game' else None,raw=raw)
        summary=dict(label=label,started_utc_ns=started,ended_utc_ns=time.time_ns(),checks_pass=all(all(v['checks'].values()) for v in result.values()),
            restoration_label=restoration,preservation_label=preservation,bounded_command_count=len(journal.read_text().splitlines()),command_timeout_s=90,
            commands_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),extra=extra)
        with (pre/(label+'-composite-audit.json')).open('x') as stream:json.dump(summary,stream,indent=2)
        assert summary['checks_pass'];print(json.dumps(dict(label=label,passed=True,bounded_command_count=summary['bounded_command_count'])),flush=True)

def current_measurement_command(proof):
    code="import pathlib,hashlib,json,stat\np=pathlib.Path('/var/lib/omega-measure/current');old=OLD;s=p.stat()\nassert p.resolve()==p and not p.is_symlink()\nassert (s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(old['device'],old['inode'],old['uid'],old['gid'],old['mode'])\nprefix={}\nfor name,row in old['files'].items():\n f=p/name;t=f.stat()\n with f.open('rb') as stream:digest=hashlib.sha256(stream.read(row['bytes'])).hexdigest()\n assert (t.st_ino,t.st_dev)==(row['inode'],row['device']) and digest==row['sha256']\n prefix[name]=dict(before_bytes=row['bytes'],current_bytes=t.st_size,prefix_sha256=digest,inode=t.st_ino)\nprint(json.dumps(dict(original_current_directory_untouched=True,owner_group_mode_unchanged=True,prefix=prefix)))\n"
    return 'sudo -n python3 -c '+shlex.quote(code.replace('OLD',repr(proof)))


def idle_release(namespace=r3.NAMESPACE):
    if namespace not in r3.NAMESPACES:raise ValueError("Only exact R4/R5 namespaces")
    import native_diagnostic_preflight_audit as idle
    r3.connection_options();ns=namespace
    P=run.ROOT/'deployment/hetzner/results'/ns;PRE=P.with_name(ns+'-preflight');B=P.with_name(ns+'-build')
    assert not (P/'manifest.json').exists() and not (P/'cleanup.json').exists()
    proofs={f.parent.name.removesuffix('-build'):json.loads(f.read_text()) for f in P.parent.glob('clean-*-build/build-proof.json')}
    round_name=r3.ROUND_NAMES[ns]
    for label in (round_name+'-idle-release-a',round_name+'-idle-release-b'):
     started=time.time_ns();primary=idle.main(label,ns);journal=PRE/(label+'-idle-audit-commands.ndjson');extra={}
     for role in ('game','bots'):
      originals=json.loads(audit.bounded_ssh(role,'sudo -n python3 -c '+shlex.quote(ORIGINALS_CODE),journal))
      before=json.loads((B/(role+'-originals-before.json')).read_text())
      assert originals==before,'Historical original backup census changed'
      sparse={}
      for name,proof in proofs.items():
       row=proof[role]
       if row.get('checkout_mode')=='rust-only-cone':
        sparse[name]=json.loads(audit.bounded_ssh(role,build.sparse_source_proof_command(row['path'],row['revision']),journal))
      # A first-budget abort has no new checkout. Prove every existing real
      # executable and dependency in either case, without requiring staging.
      elf={};dependencies={}
      for name,proof in proofs.items():
       paths=[proof[role]['path']+'/rust/target/release/'+n for n in ('omega-server','omega-load-test')]
       elf[name]=json.loads(audit.bounded_ssh(role,r3.elf_identity_command(paths,native_cargo_artifact=name!=ns),journal))
       dependencies[name]=audit.bounded_ssh(role,'ldd '+paths[0]+'; ldd '+paths[1],journal)
       assert 'not found' not in dependencies[name]
      recoveries={}
      for old in sorted(P.parent.glob('clean-*/restore.sh')):
       remote='/home/deploy/omega-results/'+old.parent.name+'/restore.sh'
       digest=audit.bounded_ssh(role,'if test -f '+remote+'; then sha256sum '+remote+'; else echo absent; fi',journal).strip()
       if role=='game':assert digest.split()[0]==hashlib.sha256(old.read_bytes()).hexdigest(),remote
       recoveries[old.parent.name]=digest.split()[0]
      details=dict(all_prior_original_files_unchanged=True,original_file_count=len(before),actual_sparse_blobs=sparse,
                   fresh_binary_elf_and_one_link_proofs=elf,dependencies=dependencies,frozen_recoveries=recoveries)
      if role=='game':
       old=json.loads((B/'storage-before-staging.json').read_text())['measurement']['measurement']
       details['original_measurement']=json.loads(audit.bounded_ssh(role,current_measurement_command(old),journal))
      extra[role]=details
     result=dict(label=label,checks_pass=primary['checks_pass'],started_utc_ns=started,ended_utc_ns=time.time_ns(),
                 command_timeout_s=90,bounded_command_count=len(journal.read_text().splitlines()),
                 commands_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),primary=primary,extra=extra,
                 scope='Unlaunched idle/preservation proof; service never stopped and no restoration was needed')
     with (PRE/(label+'-composite-audit.json')).open('x') as f:json.dump(result,f,indent=2)
     print(json.dumps(dict(label=label,passed=True,bounded_command_count=result['bounded_command_count'])),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('freeze-originals','release','idle-release'),default='release',nargs='?')
    parser.add_argument('--namespace',choices=r3.NAMESPACES,default=r3.NAMESPACE)
    args=parser.parse_args()
    if args.mode=='freeze-originals':freeze_originals(args.namespace)
    elif args.mode=='idle-release':idle_release(args.namespace)
    else:main(args.namespace)
