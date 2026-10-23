#!/usr/bin/env python3
"""Inventory idle hosts and build an exact revision in a fresh namespace; never run it."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time

import run

BASE_REVISION = 'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb'
NATIVE_R2 = 'clean-idle150-audit-r2-20261023'
NATIVE_REVISION = 'ab535731b21860fcfdc3654288dd8821eaa63450'
NATIVE_HASHES = ('de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db',
                 'a9325ad1bd90a24e3d1bdb08ce049fb5734d67471010af6f5425b104bda2f042')


def validate_sparse_reuse(namespace, revision, reuse_namespace, proof):
    if (namespace != NATIVE_R2 or revision != NATIVE_REVISION or
            reuse_namespace != 'clean-idle150-audit-r1-20261022' or proof is None or
            any(tuple(proof[r][k] for k in ('sha256', 'bot_sha256')) != NATIVE_HASHES
                or proof[r]['revision'] != revision for r in ('game', 'bots'))):
        raise ValueError('Rust-only sparse reuse is restricted to the exact proven native R2 build')


def checkout_command(source, destination, bundle, revision, sparse=False):
    """Set cone specification BEFORE checkout; ordinary full-checkout path is unchanged."""
    q = shlex.quote
    command = ('test ! -e {d}; test ! -L {d}; git clone --shared --no-checkout {s} {d}; '
               'git -C {d} fetch {b} HEAD; git -C {d} cat-file -e {r}^{{commit}}; '
               'git -C {d} merge-base --is-ancestor {r} FETCH_HEAD; ').format(
                   d=q(destination), s=q(source), b=q(bundle), r=q(revision))
    if sparse:
        command += ('git -C {d} sparse-checkout init --cone; '
                    'git -C {d} sparse-checkout set rust; ').format(d=q(destination))
    return command + 'git -C '+q(destination)+' checkout --detach '+q(revision)+'; '


def sparse_source_proof_command(destination, revision):
    # Hash actual bytes of EVERY materialized tracked file, including skip-worktree
    # entries; status alone could hide edits. Expected blobs come from pinned Git.
    code = '''import hashlib,json,pathlib,subprocess
p=pathlib.Path(DESTINATION)
def git(*args):return subprocess.check_output(['git','-C',str(p),*args])
assert git('rev-parse','HEAD').decode().strip()==REVISION
assert not git('status','--porcelain').strip()
assert git('config','--bool','core.sparseCheckoutCone').strip()==b'true'
assert git('sparse-checkout','list').decode().splitlines()==['rust']
expected=[];rust=[]
for entry in git('ls-tree','-rz','--full-tree',REVISION).split(b'\\0'):
 if not entry:continue
 meta,name=entry.split(b'\\t',1);mode,kind,oid=meta.split();name=name.decode()
 if name.startswith('rust/') or '/' not in name:
  f=p/name
  assert kind==b'blob' and f.is_file() and not f.is_symlink(),name
  content=f.read_bytes()
  assert hashlib.sha1(b'blob '+str(len(content)).encode()+b'\\0'+content).hexdigest()==oid.decode(),name
  expected.append(name)
  if name.startswith('rust/'):rust.append(name)
assert rust and 'rust/Cargo.lock' in rust and 'rust/Cargo.toml' in rust
assert {f.name for f in p.iterdir() if f.is_dir()}=={'.git','rust'}
print(json.dumps(dict(revision=REVISION,status='',cone=True,specification=(p/'.git/info/sparse-checkout').read_text(),
 directories=['rust'],tracked_file_count=len(expected),rust_file_count=len(rust),
 rust_tree=git('rev-parse','HEAD:rust').decode().strip(),all_materialized_blobs_verified=True,
 shared_object_alternates=(p/'.git/objects/info/alternates').read_text(),
 specification_sha256=hashlib.sha256((p/'.git/info/sparse-checkout').read_bytes()).hexdigest())))
'''.replace('DESTINATION', repr(destination)).replace('REVISION', repr(revision))
    return 'python3 -c '+shlex.quote(code)


def validate_revision(revision, cwd=None):
    """Allow report-only HEAD advances, but bundle only a reachable exact commit."""
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Full immutable revision required')
    resolved = subprocess.check_output(
        ['git', 'rev-parse', '--verify', revision+'^{commit}'], cwd=cwd, text=True).strip()
    if resolved != revision:
        raise ValueError('Candidate must identify the exact commit, not a tag')
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'], cwd=cwd, check=True)
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE_REVISION, revision], cwd=cwd, check=True)
    if revision == BASE_REVISION:
        raise ValueError('Candidate must be included beyond the bundle prerequisite')
    return resolved


def load_reuse_proof(namespace, revision, results_root):
    if not re.fullmatch(r'clean-[a-z0-9-]{1,65}', namespace):
        raise ValueError('Invalid reuse namespace')
    directory = results_root/(namespace+'-build')
    proof = json.loads((directory/'build-proof.json').read_text())
    expected_path = '/home/deploy/omega-'+namespace
    for role in ('game', 'bots'):
        row = proof[role]
        if row['revision'] != revision or row['path'] != expected_path:
            raise ValueError('Reuse requires the same exact revision and proven checkout')
        if any(not re.fullmatch(r'[0-9a-f]{64}', row[k]) for k in ('sha256','bot_sha256')):
            raise ValueError('Invalid prior binary hash')
    if any(proof['game'][k] != proof['bots'][k] for k in ('revision','path','sha256','bot_sha256')):
        raise ValueError('Prior both-host identities disagree')
    return proof


def reuse_binaries_command(source, destination, revision, game_sha, bot_sha):
    """Verify frozen source and both binaries before AND after real-file copies."""
    q = shlex.quote
    verify = ('test "$(git -C {s} rev-parse HEAD)" = {r}; '
              'test -z "$(git -C {s} status --porcelain)"; ').format(s=q(source),r=q(revision))
    for name, digest in (('omega-server',game_sha),('omega-load-test',bot_sha)):
        path = source+'/rust/target/release/'+name
        verify += ('test -f {p}; test ! -L {p}; '
                   'test "$(sha256sum {p} | cut -d " " -f 1)" = {h}; ').format(p=q(path),h=q(digest))
    command = verify+'mkdir -p '+q(destination+'/rust/target/release')+'; '
    for name in ('omega-server','omega-load-test'):
        src = source+'/rust/target/release/'+name
        dst = destination+'/rust/target/release/'+name
        command += ('test ! -e {d}; test ! -L {d}; cp --reflink=auto {s} {d}; test ! -L {d}; '
                    'test ! {s} -ef {d}; ').format(s=q(src),d=q(dst))
    return command+verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--namespace', default='clean-strategy150-r1-20261022')
    parser.add_argument('--reuse-build-namespace', help='Future cells only: copy verified same-revision binaries into a fresh checkout')
    parser.add_argument('--rust-only-sparse-checkout', action='store_true',
                        help='Exact native R2 only: materialize the complete Rust cone before verified binary reuse')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Full immutable revision required')
    if not re.fullmatch(r'clean-[a-z0-9-]{1,65}', args.namespace):
        parser.error('Invalid namespace')
    assert subprocess.check_output(['git','branch','--show-current'],text=True).strip() == 'fix/load-test-clean-runs'
    validate_revision(args.revision)
    reuse = load_reuse_proof(args.reuse_build_namespace, args.revision,
                           run.ROOT/'deployment/hetzner/results') if args.reuse_build_namespace else None
    if args.rust_only_sparse_checkout:
        validate_sparse_reuse(args.namespace, args.revision, args.reuse_build_namespace, reuse)
    os.umask(0o077)
    directory = run.ROOT/'deployment/hetzner/results'/(args.namespace+'-build')
    directory.mkdir(mode=0o700,exist_ok=False)
    dest = '/home/deploy/omega-' + args.namespace
    remote_bundle = '/home/deploy/' + args.namespace + '.bundle'

    def ssh(role, command, timeout=90):
        host = run.HOSTS[role]
        try:
            result = subprocess.run(['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,
                                     host['ssh_user']+'@'+host['ipv4'],command],
                                    capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            (directory/(role+'-timeout.json')).write_text(json.dumps(dict(command=command,stdout=str(error.stdout),stderr=str(error.stderr))))
            raise RuntimeError(role+' timed out; private exact output retained') from None
        with (directory/(role+'-commands.ndjson')).open('a') as stream:
            stream.write(json.dumps(dict(utc_ns=time.time_ns(),command=command,rc=result.returncode,
                                         stdout=result.stdout,stderr=result.stderr))+'\n')
        if result.returncode:
            raise RuntimeError(role+' remote failure; exact private journal retained')
        return result.stdout

    def inventory(role):
        commands = {
            'processes':'ps -eo pid,comm,args',
            'units':"systemctl list-units --all --no-legend 'omega-*'",
            'disk':'df --output=avail -B1 /home/deploy | tail -1',
            'buffers':'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
            'toolchain':'source /home/deploy/.cargo/env; rustc -Vv; cargo -V; uname -a',
            'build_environment':"env | sort | sed -n '/^RUST/p; /^CARGO/p; /^CC=/p; /^CFLAGS=/p; /^LDFLAGS=/p'",
            'cargo_config':"for p in /home/deploy/.cargo/config /home/deploy/.cargo/config.toml; do if test -f $p; then cat $p; fi; done",
            'artifacts':"find /home/deploy/omega-* -maxdepth 5 -path '*/target/release/omega-*' -type f ! -name '*.d' -exec sha256sum {} \\; | sort",
            'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",
            'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
            'namespace_absent':'test ! -e /home/deploy/omega-results/'+args.namespace+' && test ! -e '+dest+' && echo absent',
            'maintenance':'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
            'qdisc':'tc -j qdisc show dev eth0','egress':'tc -j filter show dev eth0 egress',
            'ingress':'tc -j filter show dev eth0 ingress','nft':'sudo -n nft list ruleset',
        }
        if role == 'game':
            commands.update(metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',
                config='sha256sum /etc/omega-loadtest/arena.json',service='systemctl is-active omega-loadtest-arena.service',
                exe='pid=$(systemctl show omega-loadtest-arena.service -p MainPID --value); sha256sum /proc/$pid/exe',
                sockets='sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"',unit='systemctl cat omega-loadtest-arena.service')
        data = {key:ssh(role,command) for key,command in commands.items()}
        (directory/(role+'-before.json')).write_text(json.dumps(data,indent=2))
        assert int(data['disk']) > 8*1024**3, role+' disk guard'
        assert not any(' active ' in line and any(x in line for x in ('swarm','capture','collect','restore.timer')) for line in data['units'].splitlines()), 'active ownership'
        assert 'rustc 1.95.0' in data['toolchain'] and 'host: aarch64-unknown-linux-gnu' in data['toolchain']
        assert not data['build_environment'].strip() and not data['cargo_config'].strip(), 'nonbaseline compiler environment'
        for line in data['processes'].splitlines()[1:]:
            parts = line.split(None,2)
            if len(parts)<3 or parts[1] in ('bash','sshd','sshd-session'):continue
            assert parts[1] not in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') and not any(x in parts[2] for x in ('host_collect.py','capture.py','flow-record','udp_generator_profile')), 'occupied host'
        for block in data['maintenance'].split('\n\n'):
            if 'Id=apt-daily.service' in block or 'Id=apt-daily-upgrade.service' in block:assert 'ActiveState=inactive' in block
        assert not json.loads(data['egress']) and not json.loads(data['ingress'])
        assert all(q['kind']=='fq_codel' for q in json.loads(data['qdisc'])) and 'omega_measure' not in data['nft']
        if role == 'game':
            assert re.search(r'^players_online 0$',data['metrics'],re.M)
            assert data['service'].strip()=='active' and data['exe'].split()[0]=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2'
            assert data['config'].split()[0]=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c'
            assert 'rb524288' in data['sockets'] and 'tb524288' in data['sockets']
        print(role+' idle/unclaimed inventory passed',flush=True)

    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(inventory,('game','bots')))
        bundle = directory/'candidate.bundle'
        subprocess.run(['git','bundle','create',str(bundle),BASE_REVISION+'..HEAD'],check=True,capture_output=True)
        subprocess.run(['git','bundle','verify',str(bundle)],check=True,capture_output=True)
        bundle_head = subprocess.check_output(['git','bundle','list-heads',str(bundle),'HEAD'],text=True).split()[0]
        subprocess.run(['git','merge-base','--is-ancestor',args.revision,bundle_head],check=True,capture_output=True)
        source = dict(revision=args.revision,tree=subprocess.check_output(['git','rev-parse',args.revision+'^{tree}'],text=True).strip(),
                      bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
                      source_archive_sha256=hashlib.sha256(subprocess.check_output(['git','archive',args.revision])).hexdigest(),
                      bundle_head=bundle_head,
                      candidate_reachable_from_bundle_head=True, bundle_verified=True,
                      checkout_mode='rust-only-cone' if args.rust_only_sparse_checkout else 'full',
                      reused_build_proof_sha256=(hashlib.sha256((run.ROOT/'deployment/hetzner/results'/
                          (args.reuse_build_namespace+'-build')/'build-proof.json').read_bytes()).hexdigest() if reuse else None),
                      local_utc_ns=time.time_ns())
        (directory/'toolchain-and-source-proof.json').write_text(json.dumps(source,indent=2))
        if args.rust_only_sparse_checkout:
            import native_diagnostic_storage as storage
            # Before the first remote write: full sparse source/bundle/binary staging,
            # original executable + measured evidence preservation and bounded run.
            copied_binary_bytes = sum(int(ssh('game','stat -c %s '+reuse['game']['path']+
                                             '/rust/target/release/'+name))
                                      for name in ('omega-server','omega-load-test'))
            allowance = storage.sparse_checkout_allowance(args.revision,bundle.stat().st_size,copied_binary_bytes)
            storage.check(ssh,'/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server',
                          allowance,directory/'storage-before-staging.json')
        def build(role):
            if args.rust_only_sparse_checkout:
                host=run.HOSTS[role]
                transfer=subprocess.run(['scp','-q','-i',str(run.KEY),*run.SSH_OPTIONS,
                    str(bundle),host['ssh_user']+'@'+host['ipv4']+':'+remote_bundle],
                    capture_output=True,text=True,timeout=60)
                if transfer.returncode:
                    raise RuntimeError(role+' bounded bundle upload failed')
                if ssh(role,'sha256sum '+remote_bundle).split()[0] != source['bundle_sha256']:
                    raise RuntimeError(role+' uploaded bundle hash mismatch')
            else:
                run.copy(role,bundle,remote_bundle)
            command = 'set -e; source /home/deploy/.cargo/env; '+checkout_command(
                '/home/deploy/omega-udp-control-cc86869',dest,remote_bundle,args.revision,args.rust_only_sparse_checkout)
            command += (
                'test -z "$(git -C {d} status --porcelain)"; test "$(git -C {d} rev-parse HEAD)" = {r}; '
                'cd {d}/rust; rustc -Vv; cargo -V; uname -a; ').format(d=dest,b=remote_bundle,r=args.revision)
            if reuse:
                row = reuse[role]
                command += reuse_binaries_command(row['path'],dest,args.revision,row['sha256'],row['bot_sha256'])
            else:
                command += 'cargo build --release --locked -j 2 -p omega-server -p omega-load-test; '
            command += 'sha256sum target/release/omega-server target/release/omega-load-test; git status --porcelain'
            output=ssh(role,command,1200)
            proof=dict(revision=args.revision,path=dest,sha256=ssh(role,'sha256sum '+dest+'/rust/target/release/omega-server').split()[0],
                       bot_sha256=ssh(role,'sha256sum '+dest+'/rust/target/release/omega-load-test').split()[0],
                       build_argv=[] if reuse else ['cargo','build','--release','--locked','-j','2','-p','omega-server','-p','omega-load-test'],
                       build_mode='verified-real-file-copy' if reuse else 'native-build',
                       checkout_mode='rust-only-cone' if args.rust_only_sparse_checkout else 'full',
                       sparse_source_proof=(json.loads(ssh(role,sparse_source_proof_command(dest,args.revision)))
                                            if args.rust_only_sparse_checkout else None),
                       reused_from=({'namespace':args.reuse_build_namespace,'proof':reuse[role]} if reuse else None),
                       build_stdout=output,utc_ns=time.time_ns())
            (directory/(role+'-build.json')).write_text(json.dumps(proof,indent=2))
            if reuse and any(proof[k] != reuse[role][k] for k in ('sha256','bot_sha256')):
                raise RuntimeError(role+' copied artifact mismatch')
            print(role+' pinned release build passed',flush=True)
            return proof
        with concurrent.futures.ThreadPoolExecutor(2) as pool:proofs=dict(zip(('game','bots'),pool.map(build,('game','bots'))))
        assert all(proofs['game'][k]==proofs['bots'][k] for k in ('revision','sha256','bot_sha256','path'))
        (directory/'build-proof.json').write_text(json.dumps(proofs,indent=2))
        print('Both-host candidate identities agree; zero workloads launched',flush=True)
    except Exception as error:
        (directory/'failure.json').write_text(json.dumps(dict(type=type(error).__name__,error=str(error))))
        print('Build/preflight blocked: '+str(error),file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
