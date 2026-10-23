#!/usr/bin/env python3
"""Exact diagnostic/ordinary verified R3 copies and storage proof. No compilation/workloads."""
import concurrent.futures
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import time
import clean_run_audit as audit
import clean_run_build as build
import native_diagnostic_storage as storage
import run

NAMESPACE = 'clean-idle150-audit-r4-20261023'
ROUND_NAMES = {NAMESPACE: 'r4', 'clean-idle150-audit-r5-20261023': 'r5',
               'clean-idle150-r2-20261023': 'ordinary-r2',
               'clean-movement50-r1-20261023': 'ordinary-movement50-r1',
               'clean-movement100-r1-20261023': 'ordinary-movement100-r1',
               'clean-movement150-r1-20261023': 'ordinary-movement150-r1',
               'clean-combat50-r1-20261023': 'ordinary-combat50-r1'}
NAMESPACES = tuple(ROUND_NAMES)
REUSE_NAMESPACE = 'clean-idle150-audit-r3-20261023'
BOT_SHA = '56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67'
REVISION = 'a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf'
GAME_SHA = build.NATIVE_HASHES[0]
PAIR_CAP = 20*1024**2
LIVE = 16*1024**2
ARCHIVE = 42*1024**2



def connection_options():
    run.SSH_OPTIONS = ['-o','BatchMode=yes','-o','ConnectTimeout=15','-o','ControlMaster=no',
                       '-o','ControlPath=none','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3']


def rename_probe_command(staging_bytes):
    if type(staging_bytes) is not int or staging_bytes <= 0:
        raise ValueError('Positive staging allowance required')
    code = '''import os,pathlib,json,hashlib,subprocess,stat
p=pathlib.Path('/var/lib/omega-measure/current');dst=pathlib.Path('/home/deploy/omega-results')
for d in (p,p.parent,dst,dst.parent):assert d.is_dir() and not d.is_symlink() and d.resolve()==d,str(d)
assert p.stat().st_dev==dst.stat().st_dev
fs=list(p.rglob('*'));assert all(not f.is_symlink() and (f.is_file() or f.is_dir()) for f in fs)
s=p.stat();v=os.statvfs(dst)
files={str(f.relative_to(p)):dict(bytes=f.stat().st_size,sha256=hashlib.file_digest(f.open('rb'),'sha256').hexdigest(),inode=f.stat().st_ino,device=f.stat().st_dev) for f in fs if f.is_file()}
print(json.dumps(dict(free_bytes=v.f_bavail*v.f_frsize,same_device=True,real_directories=True,measurement=dict(device=s.st_dev,inode=s.st_ino,uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode),files=files),staging_bytes=STAGING+((pathlib.Path('/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server').stat().st_size+4095)//4096)*4096)))
'''.replace('STAGING',repr(staging_bytes))
    return 'python3 -c '+shlex.quote(code)


def budget(measurement):
    if measurement.get('same_device') is not True or measurement.get('real_directories') is not True:
        raise ValueError('Same-device real-directory proof required before zero-copy allowance')
    free,stage = measurement['free_bytes'],measurement['staging_bytes']
    if any(type(v) is not int or v <= 0 for v in (free,stage)):
        raise ValueError('Exact positive byte measurements required')
    allowances = dict(original_measurement_additional_payload=0, staging_and_original_executable=stage,
        live_game_payload=LIVE,journal=storage.JOURNAL,role_only_archive=ARCHIVE,margin=storage.MARGIN)
    total=sum(allowances.values())
    return dict(free_bytes=free,unchanged_guard_bytes=storage.GUARD,allowances=allowances,
        combined_bytes=total,remaining_above_guard_after_allowance=free-storage.GUARD-total,
        passed=free-storage.GUARD>=total,measurement=measurement)


def check(ssh, staging_bytes, output):
    result=budget(json.loads(ssh('game',rename_probe_command(staging_bytes))))
    with pathlib.Path(output).open('x') as stream:json.dump(result,stream,indent=2)
    if not result['passed']:raise RuntimeError('R4 additive storage cannot fit above unchanged 8 GiB guard')
    return result


def elf_identity_command(paths, native_cargo_artifact=False):
    code = """import pathlib,struct,json
result={}
for name in PATHS:
 p=pathlib.Path(name);assert p.is_file() and not p.is_symlink()
 assert NATIVE or p.stat().st_nlink==1
 with p.open('rb') as stream:header=stream.read(64)
 assert header[:6]==b'\\x7fELF\\x02\\x01' and len(header)==64
 kind,machine,version=struct.unpack_from('<HHI',header,16)
 assert machine==183 and version==1 and kind in (2,3)
 result[name]=dict(format='ELF64',endianness='little',machine='AArch64',type=kind,osabi=header[7],links=p.stat().st_nlink,bytes=p.stat().st_size)
print(json.dumps(result))
""".replace('PATHS',repr(list(paths))).replace('NATIVE',repr(native_cargo_artifact))
    return 'python3 -c '+shlex.quote(code)


def prepare(namespace=NAMESPACE):
    if namespace not in NAMESPACES:raise ValueError("Only exact authorized reuse namespaces")
    connection_options();os.umask(0o077)
    pre=run.ROOT/'deployment/hetzner/results'/(namespace+'-preflight')
    directory=pre.with_name(namespace+'-build');directory.mkdir(exist_ok=False)
    dest='/home/deploy/omega-'+namespace;remote_bundle='/home/deploy/'+namespace+'.bundle'
    journal=directory/'commands.ndjson'
    ssh=lambda role,command:audit.bounded_ssh(role,command,journal)
    commands=dict(processes='ps -eo pid,comm,args',units="systemctl list-units --all --no-legend 'omega-*'",
        disk='df --output=avail -B1 /home/deploy | tail -1',
        buffers='sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
        toolchain='source /home/deploy/.cargo/env; rustc -Vv; cargo -V; uname -a; ldd --version | head -1',
        build_environment="env | sort | sed -n '/^RUST/p; /^CARGO/p; /^CC=/p; /^CFLAGS=/p; /^LDFLAGS=/p'",
        cargo_config='for p in /home/deploy/.cargo/config /home/deploy/.cargo/config.toml; do if test -f $p; then cat $p; fi; done',
        artifacts="find /home/deploy/omega-* -maxdepth 5 -path '*/target/release/omega-*' -type f ! -name '*.d' -exec sha256sum {} \\; | sort",
        prior_archives="find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",
        closed_states="find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
        namespace_absent='test ! -e /home/deploy/omega-results/'+namespace+' && test ! -e '+dest+' && test ! -L '+dest+' && echo absent',
        maintenance='systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
        qdisc='tc -j qdisc show dev eth0',egress='tc -j filter show dev eth0 egress',ingress='tc -j filter show dev eth0 ingress',nft='sudo -n nft list ruleset')
    def inventory(role):
        extra=dict(metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',config='sha256sum /etc/omega-loadtest/arena.json',
            service='systemctl is-active omega-loadtest-arena.service',exe='pid=$(systemctl show omega-loadtest-arena.service -p MainPID --value); sha256sum /proc/$pid/exe',
            sockets='sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"',unit='systemctl cat omega-loadtest-arena.service') if role=='game' else {}
        row={k:ssh(role,c) for k,c in (commands|extra).items()}
        (directory/(role+'-before.json')).write_text(json.dumps(row,indent=2))
        assert int(row['disk'])>storage.GUARD
        assert 'rustc 1.95.0' in row['toolchain'] and 'host: aarch64-unknown-linux-gnu' in row['toolchain']
        assert not row['build_environment'].strip() and not row['cargo_config'].strip()
        assert not json.loads(row['ingress']) and not json.loads(row['egress'])
        assert all(q['kind']=='fq_codel' for q in json.loads(row['qdisc'])) and 'omega_measure' not in row['nft']
        import re
        assert not any(re.search(r'\sactive\s',l) and not (role=='game' and l.strip().startswith('omega-loadtest-arena.service ')) for l in row['units'].splitlines())
        for line in row['processes'].splitlines()[1:]:
            parts=line.split(None,2)
            if len(parts)<3 or parts[1] in ('bash','sshd','sshd-session'):continue
            assert parts[1] not in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') and not any(x in parts[2] for x in ('host_collect.py','capture.py','flow-record','udp_generator_profile'))
        for block in row['maintenance'].split('\n\n'):
            if 'Id=apt-daily.service' in block or 'Id=apt-daily-upgrade.service' in block:assert 'ActiveState=inactive' in block
        if role=='game':
            assert re.search(r'^players_online 0$',row['metrics'],re.M) and row['service'].strip()=='active'
            assert row['exe'].split()[0]=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2'
            assert row['config'].split()[0]=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c'
            assert 'rb524288' in row['sockets'] and 'tb524288' in row['sockets']
        return role,row
    inventories=dict(concurrent.futures.ThreadPoolExecutor(2).map(inventory,('game','bots')))
    # Both native hosts must have exactly the same compiler, libc and architecture.
    assert inventories['game']['toolchain'].split('uname')[0].split('Linux')[0]==inventories['bots']['toolchain'].split('Linux')[0]
    assert inventories['game']['toolchain'].splitlines()[-1]==inventories['bots']['toolchain'].splitlines()[-1]
    build.validate_revision(REVISION)
    bundle=directory/'candidate.bundle'
    subprocess.run(['git','bundle','create',str(bundle),build.BASE_REVISION+'..HEAD'],check=True,capture_output=True)
    subprocess.run(['git','bundle','verify',str(bundle)],check=True,capture_output=True)
    reuse=build.load_reuse_proof(REUSE_NAMESPACE,REVISION,pre.parent)
    validate_reuse(namespace,REVISION,REUSE_NAMESPACE,reuse)
    sizes={}
    for role in ('game','bots'):
        src=reuse[role]['path']
        # Actual source bytes and Cargo files, not only git status.
        old_sparse=json.loads(ssh(role,build.sparse_source_proof_command(src,REVISION)))
        (directory/(role+'-reuse-sparse.json')).write_text(json.dumps(old_sparse,indent=2))
        for name,digest in (('omega-server',GAME_SHA),('omega-load-test',BOT_SHA)):
            path=src+'/rust/target/release/'+name
            assert ssh(role,'sha256sum '+path).split()[0]==digest
            sizes[role,name]=int(ssh(role,'stat -c %s '+path))
        assert sum(sizes[role,n] for n in ('omega-server','omega-load-test'))<=PAIR_CAP
    assert all(sizes['game',n]==sizes['bots',n] for n in ('omega-server','omega-load-test'))
    staging=storage.sparse_checkout_allowance(REVISION,bundle.stat().st_size,sum(sizes['game',n] for n in ('omega-server','omega-load-test')))
    check(ssh,staging,directory/'storage-before-staging.json')
    source=dict(revision=REVISION,tree=subprocess.check_output(['git','rev-parse',REVISION+'^{tree}'],text=True).strip(),
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),bundle_verified=True,
        checkout_mode='rust-only-cone',native_build_origin='bots',game_artifact_mode='verified-existing-build-copy',build_mode='verified-existing-build-copy',reuse_namespace=REUSE_NAMESPACE,
        reused_build_proof_sha256=hashlib.sha256((pre.parent/(REUSE_NAMESPACE+'-build')/'build-proof.json').read_bytes()).hexdigest(),
        pair_cap_bytes=PAIR_CAP,new_compilation=False,staging_bytes=staging)
    (directory/'toolchain-and-source-proof.json').write_text(json.dumps(source,indent=2))
    def transfer(role,src,dst,download=False):
        host=run.HOSTS[role];address=host['ssh_user']+'@'+host['ipv4']+':'
        result=subprocess.run(['scp','-q','-i',str(run.KEY),*run.SSH_OPTIONS,address+src if download else str(src),str(dst) if download else address+dst],capture_output=True,text=True,timeout=90)
        if result.returncode:raise RuntimeError(role+' bounded build transfer failed')
    for role in ('game','bots'):
        transfer(role,bundle,remote_bundle)
        assert ssh(role,'sha256sum '+remote_bundle).split()[0]==source['bundle_sha256']
        ssh(role,'set -e; '+build.checkout_command('/home/deploy/omega-udp-control-cc86869',dest,remote_bundle,REVISION,True))
        sparse=json.loads(ssh(role,build.sparse_source_proof_command(dest,REVISION)))
        (directory/(role+'-sparse-before.json')).write_text(json.dumps(sparse,indent=2))
    proofs={}
    for role in ('game','bots'):
        src=reuse[role]['path']
        ssh(role,'set -e; '+build.reuse_binaries_command(src,dest,REVISION,GAME_SHA,BOT_SHA))
        sparse=json.loads(ssh(role,build.sparse_source_proof_command(dest,REVISION)))
        identity=json.loads(ssh(role,elf_identity_command([dest+'/rust/target/release/'+n for n in ('omega-server','omega-load-test')])))
        for name,digest in (('omega-server',GAME_SHA),('omega-load-test',BOT_SHA)):
            path=dest+'/rust/target/release/'+name
            assert ssh(role,'sha256sum '+path).split()[0]==digest
            assert identity[path]['links']==1 and identity[path]['bytes']==sizes[role,name]
        row=dict(revision=REVISION,path=dest,sha256=GAME_SHA,bot_sha256=BOT_SHA,
            build_mode='verified-existing-build-copy',game_artifact_mode='verified-existing-build-copy',
            native_build_origin='bots',new_compilation=False,build_argv=[],
            reused_from=dict(namespace=REUSE_NAMESPACE,proof=reuse[role]),
            checkout_mode='rust-only-cone',sparse_source_proof=sparse,file_identity=identity,
            dependencies=ssh(role,'ldd '+dest+'/rust/target/release/omega-server; ldd '+dest+'/rust/target/release/omega-load-test'),
            binary_bytes={n:sizes[role,n] for n in ('omega-server','omega-load-test')},utc_ns=time.time_ns())
        with (directory/(role+'-build.json')).open('x') as stream:json.dump(row,stream,indent=2)
        proofs[role]=row
    with (directory/'build-proof.json').open('x') as stream:json.dump(proofs,stream,indent=2)
    print(namespace+': both independent real-file copies verified; R3 native origin bots; no new compilation or workload',flush=True)


def validate_reuse(namespace,revision,reuse_namespace,proof):
    if namespace not in NAMESPACES or revision!=REVISION or reuse_namespace!=REUSE_NAMESPACE:
        raise ValueError('Only exact authorized copies from proven R3 source and binaries')
    for role in ('game','bots'):
        row=proof[role]
        if (row['revision']!=REVISION or row['path']!='/home/deploy/omega-'+REUSE_NAMESPACE or
            row['sha256']!=GAME_SHA or row['bot_sha256']!=BOT_SHA or row.get('native_build_origin')!='bots'):
            raise ValueError('R3 reuse identity or native origin mismatch')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',choices=NAMESPACES,default=NAMESPACE)
    prepare(parser.parse_args().namespace)
