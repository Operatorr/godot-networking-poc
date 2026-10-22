#!/usr/bin/env python3
"""Read-only exact clean-candidate inventory, or narrowly reclaim its Cargo intermediates.

No executable, source, original/frozen build or evidence removal is supported.
The caller journals exact command/output and prior artifact/archive preservation.
"""
import hashlib
import pathlib
import shutil
import subprocess

INTERMEDIATES=('deps','build','incremental','.fingerprint','examples')

def candidate(row):
    p=pathlib.Path(row['path'])
    if (not p.name.startswith('omega-clean-') or p.parent!=pathlib.Path('/home/deploy')
            or p.is_symlink() or p.resolve()!=p):raise ValueError('Only exact real clean-* candidates')
    revision=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
    status=subprocess.check_output(['git','-C',str(p),'status','--porcelain'],text=True)
    if revision!=row['revision'] or status:raise ValueError('Source identity mismatch')
    hashes={}
    for name,key in [('omega-server','sha256'),('omega-load-test','bot_sha256')]:
        f=p/'rust/target/release'/name
        if not f.is_file() or f.is_symlink():raise ValueError('Executable missing or symlink')
        hashes[name]=hashlib.file_digest(f.open('rb'),'sha256').hexdigest()
        if hashes[name]!=row[key]:raise ValueError('Executable identity mismatch')
    dirs={}
    for name in INTERMEDIATES:
        f=p/'rust/target/release'/name
        if f.is_symlink():raise ValueError('Intermediate symlink')
        if f.exists():
            if not f.is_dir() or f.resolve()!=f:raise ValueError('Intermediate not real directory')
            dirs[str(f)]=int(subprocess.check_output(['du','-s','-B1',str(f)],text=True).split()[0])
    return dict(revision=revision,status=status,hashes=hashes,intermediates=dirs,
                free_bytes=shutil.disk_usage('/home/deploy').free)

def reclaim(row):
    before=candidate(row);removed=[]
    for path,allocated in before['intermediates'].items():
        f=pathlib.Path(path)
        if f.name not in INTERMEDIATES or f.parent!=pathlib.Path(row['path'])/'rust/target/release':
            raise ValueError('Non-intermediate deletion')
        shutil.rmtree(f)
        removed.append(dict(path=path,allocated_bytes_before=allocated))
    after=candidate(row)
    if any(before[k]!=after[k] for k in ('revision','status','hashes')):raise ValueError('Preservation failed')
    return dict(before=before,after=after,removed=removed)
