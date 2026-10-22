#!/usr/bin/env python3
"""Pinned AoI candidate build; no workload execution or service changes."""
import sys, pathlib, json, time, os, re, subprocess, hashlib, concurrent.futures, shlex
sys.path.insert(0,str(pathlib.Path.cwd()/'scripts/load_campaign'))
import run
ROOT=run.ROOT
D=ROOT/'deployment/hetzner/results/aoi150-20261022-build'
D.mkdir(mode=0o700,exist_ok=False)
os.umask(0o077)
REV='4c33a3e0bdccad352f82bbe00cdabf8e907a84d8'
DEST='/home/deploy/omega-aoi150-20261022'
def ssh(role,cmd,timeout=90):
 h=run.HOSTS[role]
 p=subprocess.run(['ssh','-i',str(run.KEY),*run.SSH_OPTIONS,h['ssh_user']+'@'+h['ipv4'],cmd],capture_output=True,text=True,timeout=timeout)
 with (D/(role+'-commands.ndjson')).open('a') as f:f.write(json.dumps(dict(utc_ns=time.time_ns(),command=cmd,rc=p.returncode,stdout=p.stdout,stderr=p.stderr))+'\n')
 if p.returncode:raise RuntimeError(role+' remote failure; private journal retained')
 return p.stdout
def inventory(role):
 cmds={'processes':'ps -eo pid,comm,args','units':"systemctl list-units --all --no-legend 'omega-*'",'disk':'df --output=avail -B1 /home/deploy | tail -1','buffers':'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max','toolchain':'source /home/deploy/.cargo/env; rustc -Vv; cargo -V; uname -a','build_environment':"env | sort | sed -n '/^RUST/p; /^CARGO/p; /^CC=/p; /^CFLAGS=/p; /^LDFLAGS=/p'",'cargo_config':"for p in /home/deploy/.cargo/config /home/deploy/.cargo/config.toml; do if test -f $p; then cat $p; fi; done",'artifacts':"find /home/deploy/omega-* -path '*/target/release/omega-*' -type f ! -name '*.d' -maxdepth 5 -exec sha256sum {} \\; | sort",'prior_archives':"find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) -exec sha256sum {} \\; | sort",'closed_states':"find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",'namespace_absent':'test ! -e /home/deploy/omega-results/aoi150-20261022 && test ! -e '+DEST+' && echo absent','maintenance':'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState','qdisc':'tc -j qdisc show dev eth0','egress':'tc -j filter show dev eth0 egress','ingress':'tc -j filter show dev eth0 ingress','nft':'sudo -n nft list ruleset'}
 if role=='game':cmds.update(metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',config='sha256sum /etc/omega-loadtest/arena.json',service='systemctl is-active omega-loadtest-arena.service',exe='pid=$(systemctl show omega-loadtest-arena.service -p MainPID --value); sha256sum /proc/$pid/exe',sockets='sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"',unit='systemctl cat omega-loadtest-arena.service')
 data={k:ssh(role,c) for k,c in cmds.items()}
 (D/(role+'-before.json')).write_text(json.dumps(data,indent=2))
 assert int(data['disk'])>8*1024**3
 assert not any(' active ' in line and ('swarm' in line or 'capture' in line or 'collect' in line or 'restore.timer' in line) for line in data['units'].splitlines()), 'owned units active'
 assert 'rustc 1.95.0' in data['toolchain'] and 'host: aarch64-unknown-linux-gnu' in data['toolchain']
 assert not data['build_environment'].strip() and not data['cargo_config'].strip(), 'nonbaseline build environment'
 for line in data['processes'].splitlines()[1:]:
  a=line.split(None,2)
  if len(a)<3 or a[1] in ('bash','sshd','sshd-session'):continue
  assert a[1] not in ('omega-load-test','tcpdump','perf','bpftrace','cargo','rustc','apt','apt-get','dpkg') and not any(s in a[2] for s in ('host_collect.py','capture.py','flow-record','udp_generator_profile')), 'occupied host'
 for b in data['maintenance'].split('\n\n'):
  if 'Id=apt-daily.service' in b or 'Id=apt-daily-upgrade.service' in b:assert 'ActiveState=inactive' in b
 assert not json.loads(data['egress']) and not json.loads(data['ingress'])
 assert all(q['kind']=='fq_codel' for q in json.loads(data['qdisc'])) and 'omega_measure' not in data['nft']
 if role=='game':
  assert re.search(r'^players_online 0$',data['metrics'],re.M)
  assert data['service'].strip()=='active' and data['exe'].split()[0]=='f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2'
  assert data['config'].split()[0]=='bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c'
  assert 'rb524288' in data['sockets'] and 'tb524288' in data['sockets']
 print(role+' idle prebuild inventory passed',flush=True)
 return data
if __name__=='__main__':
 try:
  with concurrent.futures.ThreadPoolExecutor(2) as pool: states=dict(zip(('game','bots'),pool.map(inventory,('game','bots'))))
  assert subprocess.check_output(['git','rev-parse',REV],text=True).strip()==REV
  assert subprocess.check_output(['git','branch','--show-current'],text=True).strip()=='fix/strict-aoi-diagnosis'
  bundle=D/'candidate.bundle'
  subprocess.run(['git','bundle','create',str(bundle),'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb..refs/heads/fix/strict-aoi-diagnosis'],check=True,capture_output=True)
  build="set -e; source /home/deploy/.cargo/env; test ! -e {d}; git clone --shared --no-checkout /home/deploy/omega-udp-control-cc86869 {d}; git -C {d} fetch /home/deploy/aoi150-20261022.bundle refs/heads/fix/strict-aoi-diagnosis; git -C {d} checkout --detach {r}; test -z \"$(git -C {d} status --porcelain)\"; test \"$(git -C {d} rev-parse HEAD)\" = {r}; cd {d}/rust; rustc -Vv; cargo -V; uname -a; cargo build --release --locked -j 2 -p omega-server -p omega-load-test; sha256sum target/release/omega-server; git status --porcelain".format(d=DEST,r=REV)
  def one(role):
   run.copy(role,bundle,'/home/deploy/aoi150-20261022.bundle')
   out=ssh(role,build,1200)
   sha=ssh(role,'sha256sum '+DEST+'/rust/target/release/omega-server').split()[0]
   bot_sha=ssh(role,'sha256sum '+DEST+'/rust/target/release/omega-load-test').split()[0]
   proof=dict(bot_sha256=bot_sha,revision=REV,path=DEST,sha256=sha,build_argv=['cargo','build','--release','--locked','-j','2','-p','omega-server','-p','omega-load-test'],build_stdout=out,utc_ns=time.time_ns())
   (D/(role+'-build.json')).write_text(json.dumps(proof,indent=2))
   print(role+' candidate built '+sha,flush=True)
   return proof
  with concurrent.futures.ThreadPoolExecutor(2) as pool: proofs=dict(zip(('game','bots'),pool.map(one,('game','bots'))))
  assert proofs['game']['sha256']==proofs['bots']['sha256'] and proofs['game']['bot_sha256']==proofs['bots']['bot_sha256'],'candidate build mismatch'
  (D/'build-proof.json').write_text(json.dumps(proofs,indent=2))
  print('Both candidate hashes identical; no workload launched',flush=True)
 except Exception as e:
  (D/'failure.json').write_text(json.dumps({'type':type(e).__name__,'error':str(e)}))
  print('Prebuild/build failed: '+type(e).__name__+'; private evidence retained',flush=True)
  sys.exit(1)
