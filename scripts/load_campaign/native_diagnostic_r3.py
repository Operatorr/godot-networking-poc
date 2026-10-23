#!/usr/bin/env python3
"""Exact R3 native bot-host build and read-only additive storage proof. No workloads."""
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

NAMESPACE = 'clean-idle150-audit-r3-20261023'
REVISION = 'a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf'
GAME_SHA = build.NATIVE_HASHES[0]
PAIR_CAP = 20*1024**2
LIVE = 32*1024**2
ARCHIVE = 58*1024**2
BOT_BUILD_ALLOWANCE = 2*1024**3


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
    if not result['passed']:raise RuntimeError('R3 additive storage cannot fit above unchanged 8 GiB guard')
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


def prepare():
    connection_options();os.umask(0o077)
    pre=run.ROOT/'deployment/hetzner/results'/(NAMESPACE+'-preflight')
    directory=pre.with_name(NAMESPACE+'-build');directory.mkdir(exist_ok=False)
    dest='/home/deploy/omega-'+NAMESPACE;remote_bundle='/home/deploy/'+NAMESPACE+'.bundle'
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
        namespace_absent='test ! -e /home/deploy/omega-results/'+NAMESPACE+' && test ! -e '+dest+' && test ! -L '+dest+' && echo absent',
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
    assert int(inventories['bots']['disk'])-storage.GUARD>BOT_BUILD_ALLOWANCE
    build.validate_revision(REVISION)
    bundle=directory/'candidate.bundle'
    subprocess.run(['git','bundle','create',str(bundle),build.BASE_REVISION+'..HEAD'],check=True,capture_output=True)
    subprocess.run(['git','bundle','verify',str(bundle)],check=True,capture_output=True)
    staging=storage.sparse_checkout_allowance(REVISION,bundle.stat().st_size,PAIR_CAP)
    check(ssh,staging,directory/'storage-before-staging.json')
    source=dict(revision=REVISION,tree=subprocess.check_output(['git','rev-parse',REVISION+'^{tree}'],text=True).strip(),
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),bundle_verified=True,
        checkout_mode='rust-only-cone',native_build_origin='bots',game_artifact_mode='verified-native-bot-host-copy',
        pair_cap_bytes=PAIR_CAP,bot_build_allowance_bytes=BOT_BUILD_ALLOWANCE,staging_bytes=staging)
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
    # Detached native build is observed through bounded calls; never a game-host compilation.
    build_command='source /home/deploy/.cargo/env; cd '+dest+'/rust; mkdir -p target; timeout 1100s cargo build --release --locked -j 2 -p omega-server -p omega-load-test > '+dest+'/rust/target/native-build.log 2>&1; rc=$?; printf "%s\\n" "$rc" > '+dest+'/rust/target/native-build.exit'
    ssh('bots','set -e; mkdir -p '+dest+'/rust/target; test ! -e '+dest+'/rust/target/native-build.log; nohup setsid bash -c '+shlex.quote(build_command)+' </dev/null >/dev/null 2>&1 & echo $! > '+dest+'/rust/target/native-build.pid')
    for _ in range(110):
        result=ssh('bots','if test -f '+dest+'/rust/target/native-build.exit; then cat '+dest+'/rust/target/native-build.exit; else echo running; fi')
        if result.strip()!='running':break
        free=int(ssh('bots','df --output=avail -B1 /home/deploy | tail -1'))
        if free<storage.GUARD or int(inventories['bots']['disk'])-free>BOT_BUILD_ALLOWANCE:
            ssh('bots','pid=$(cat '+dest+'/rust/target/native-build.pid); kill -TERM -- -"$pid"')
            raise RuntimeError('Bot bounded build allowance failed; exact new build group stopped')
        time.sleep(10)
    assert result.strip()=='0','Native build did not succeed; no workload authorized'
    names=('omega-server','omega-load-test');digests={};sizes={}
    transit=directory/'native-transit';transit.mkdir()
    for name in names:
        remote=dest+'/rust/target/release/'+name
        digests[name]=ssh('bots','sha256sum '+remote).split()[0]
        sizes[name]=int(ssh('bots','stat -c %s '+remote))
    assert digests['omega-server']==GAME_SHA and sum(sizes.values())<=PAIR_CAP
    ssh('game','test ! -e '+dest+'/rust/target; mkdir -p '+dest+'/rust/target/release')
    for name in names:
        remote=dest+'/rust/target/release/'+name;local=transit/name
        transfer('bots',remote,local,True)
        assert hashlib.sha256(local.read_bytes()).hexdigest()==digests[name] and local.stat().st_nlink==1
        transfer('game',local,remote)
        ssh('game','chmod 755 '+remote+'; test ! -L '+remote+'; test "$(stat -c %h '+remote+')" = 1')
        assert ssh('game','sha256sum '+remote).split()[0]==digests[name]
    transfer('bots',dest+'/rust/target/native-build.log',directory/'native-build.log',True)
    complete_proof()


def complete_proof():
    """Resume identity-only collection after a missing file utility; no build or transfer."""
    connection_options()
    directory=run.ROOT/'deployment/hetzner/results'/(NAMESPACE+'-build')
    if (directory/'build-proof.json').exists():raise FileExistsError('Build proof sealed')
    dest='/home/deploy/omega-'+NAMESPACE
    ssh=lambda role,command:audit.bounded_ssh(role,command,directory/'proof-completion-commands.ndjson')
    assert ssh('bots','cat '+dest+'/rust/target/native-build.exit').strip()=='0'
    expected={'omega-server':GAME_SHA,'omega-load-test':'56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67'}
    proofs={}
    for role in ('game','bots'):
        checkpoint=directory/(role+'-build.json')
        if checkpoint.exists():
            row=json.loads(checkpoint.read_text())
            assert row['revision']==REVISION and row['path']==dest
            assert row['sha256']==expected['omega-server'] and row['bot_sha256']==expected['omega-load-test']
            assert row['sparse_source_proof']['all_materialized_blobs_verified']
            proofs[role]=row
            continue
        sizes={}
        for name,digest in expected.items():
            path=dest+'/rust/target/release/'+name
            assert ssh(role,'sha256sum '+path).split()[0]==digest
            sizes[name]=int(ssh(role,'stat -c %s '+path))
        assert sum(sizes.values())<=PAIR_CAP
        sparse=json.loads(ssh(role,build.sparse_source_proof_command(dest,REVISION)))
        baseline=json.loads((directory/(role+'-before.json')).read_text())
        row=dict(revision=REVISION,path=dest,sha256=expected['omega-server'],bot_sha256=expected['omega-load-test'],
            native_build_origin='bots',game_artifact_mode='verifiednativebot-hostcopy',
            build_mode='native-build' if role=='bots' else 'verifiednativebot-hostcopy',
            build_argv=['cargo','build','--release','--locked','-j','2','-p','omega-server','-p','omega-load-test'] if role=='bots' else [],
            checkout_mode='rust-only-cone',sparse_source_proof=sparse,
            dependencies=ssh(role,'ldd '+dest+'/rust/target/release/omega-server; ldd '+dest+'/rust/target/release/omega-load-test'),
            file_identity=json.loads(ssh(role,elf_identity_command([dest+'/rust/target/release/'+n for n in expected],native_cargo_artifact=role=='bots'))),
            toolchain=baseline['toolchain'],binary_bytes=sizes,utc_ns=time.time_ns(),
            proof_completion='identity only; no repeated native build or binary transfer')
        with (directory/(role+'-build.json')).open('x') as stream:json.dump(row,stream,indent=2)
        proofs[role]=row
    objects=ssh('bots','find '+dest+'/rust/target/release -type f -exec sha256sum {} \\;')
    with (directory/'native-object-manifest.txt').open('x') as stream:stream.write(objects)
    with (directory/'build-proof.json').open('x') as stream:json.dump(proofs,stream,indent=2)
    print(json.dumps(dict(build_passed=True,source=REVISION,game_sha256=expected['omega-server'],bot_sha256=expected['omega-load-test'],native_build_origin='bots')),flush=True)

if __name__=='__main__':prepare()
