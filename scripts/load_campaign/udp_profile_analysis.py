#!/usr/bin/env python3
"""Private, deterministic analysis for the single frozen CPU profile."""
import sys,pathlib,json,gzip,csv,re,statistics,hashlib,datetime
ROOT=pathlib.Path.cwd();P=ROOT/'deployment/hetzner/results/udp-profile-20261021'
sys.path.insert(0,str(ROOT/'scripts/load_campaign'));import cpu_report
manifest=json.loads((P/'manifest.json').read_text());guard=json.loads((P/'extracted/bots/guard-result.json').read_text())
ticks=list(csv.DictReader((P/'extracted/game/ticks.csv').open()))
start=json.loads((P/'extracted/bots/workload-start.json').read_text())['utc_ns'];end=guard['ended_utc_ns'];out={'swarm_start_utc_ns':start,'guard_end_utc_ns':end,'guard_elapsed_s':guard['elapsed_s'],'ramp_input_cadence':None,'generator_valid':None,'phase2_reached':False,'hosts':{}}
def counters(text):
 lines=text.splitlines()
 for a,b in zip(lines[::2],lines[1::2]):
  if a.startswith('Udp:'):return dict(zip(a.split()[1:],map(int,b.split()[1:])))
def sockets(text):
 result=[];lines=text.splitlines()
 for idx,line in enumerate(lines):
  if 'omega-' not in line or idx+1>=len(lines):continue
  identity=re.search(r'users:\(\("([^"]+)",pid=(\d+),fd=(\d+)\)\).*ino:(\d+)',line)
  mem=re.search(r'skmem:\(([^)]+)\)',lines[idx+1])
  if not identity or not mem:raise ValueError('Unparsed socket identity')
  values={m[1]:int(m[2]) for m in re.finditer(r'([a-z]+)(\d+)',mem[1])}
  values.update(comm=identity[1],pid=int(identity[2]),fd=int(identity[3]),inode=int(identity[4]),recv_q=int(line.split()[1]))
  result.append(values)
 return result
for role in ('game','bots'):
 directory=P/'extracted'/role
 with gzip.open(directory/'host.ndjson.gz','rt') as f:rows=[json.loads(x) for x in f]
 a,b=counters(rows[0]['net/snmp']),counters(rows[-1]['net/snmp'])
 active=[r for r in rows if start<=r['utc_ns']<=end]
 cpu,points=cpu_report.summarize_host(active,active[0],active[-1])
 totals={};observations=[];socket_onset=None;host_onset=None
 prev=rows[0]
 for r in rows:
  observed=sockets(r['ss']['stdout'])
  for s in observed:
   key=(s['pid'],s['inode']);totals[key]=max(s['d'],totals.get(key,0))
  observations.extend(observed)
  if socket_onset is None and any(s['d']>0 for s in observed):
   match=[t for t in ticks if prev['socket_before_utc_ns']<=int(t['utc_ns'])<=r['socket_after_utc_ns']]
   socket_onset={'socket_before_ns':prev['socket_before_utc_ns'],'socket_after_ns':r['socket_after_utc_ns'],'elapsed_since_swarm_s':(r['socket_after_utc_ns']-start)/1e9,'socket_drops_observed':sum(s['d'] for s in observed),'authenticated_min':min((int(t['authenticated']) for t in match),default=None),'authenticated_max':max((int(t['authenticated']) for t in match),default=None),'sockets_with_drops':[{k:s[k] for k in ('pid','inode','d','r','rb','recv_q')} for s in observed if s['d']>0]}
  if host_onset is None and counters(r['net/snmp'])['RcvbufErrors']>counters(prev['net/snmp'])['RcvbufErrors']:
   match=[t for t in ticks if prev['utc_ns']<=int(t['utc_ns'])<r['utc_ns']]
   host_onset={'start_ns':prev['utc_ns'],'end_ns':r['utc_ns'],'elapsed_end_since_swarm_s':(r['utc_ns']-start)/1e9,'delta':counters(r['net/snmp'])['RcvbufErrors']-counters(prev['net/snmp'])['RcvbufErrors'],'authenticated_min':min((int(t['authenticated']) for t in match),default=None),'authenticated_max':max((int(t['authenticated']) for t in match),default=None),'cpu':cpu_report.interval(prev,r)}
  prev=r
 final_sockets=sockets((directory/'final-sockets.txt').read_text())
 for s in final_sockets:totals[(s['pid'],s['inode'])]=max(s['d'],totals.get((s['pid'],s['inode']),0))
 seconds=(rows[-1]['utc_ns']-rows[0]['utc_ns'])/1e9
 collector_cpu={k:(rows[-1]['collector_cpu_s'][k]-rows[0]['collector_cpu_s'][k])/seconds*100 for k in ('self','children')}
 result={'samples':len(rows),'host_start_ns':rows[0]['utc_ns'],'host_end_ns':rows[-1]['utc_ns'],'host_interval_s':seconds,'udp_before':a,'udp_after':b,'udp_delta':{k:b[k]-a[k] for k in a},'first_host_receive_error':host_onset,'first_observed_socket_drop':socket_onset,'observed_process_socket_count':len(totals),'sum_max_observed_socket_drops':sum(totals.values()),'sockets_observed_dropping':sum(v>0 for v in totals.values()),'final_sockets':final_sockets,'effective_rb_values':sorted(set(s['rb'] for s in observations)),'effective_tb_values':sorted(set(s['tb'] for s in observations)),'max_sampled_receive_memory':max((s['r'] for s in observations),default=None),'max_sampled_recv_q':max((s['recv_q'] for s in observations),default=None),'socket_failures':sum(r['ss']['rc']!=0 for r in rows),'cpu_active_only':cpu,'collector_cpu_percent_one_core':collector_cpu,'sample_duration_ms_mean':statistics.mean(r['total_sample_duration_ns'] for r in rows)/1e6,'sample_duration_ms_max':max(r['total_sample_duration_ns'] for r in rows)/1e6,'interface_delta':{k:int(rows[-1]['interface'][k])-int(rows[0]['interface'][k]) for k in rows[0]['interface']},'qdisc_first':json.loads(rows[0]['tc']['stdout']),'qdisc_last':json.loads(rows[-1]['tc']['stdout'])}
 out['hosts'][role]=result
work=[int(t['work_ns'])/1e6 for t in ticks if start<=int(t['utc_ns'])<=end];lag=[float(t['accumulator_lag_s']) for t in ticks if start<=int(t['utc_ns'])<=end]
players=[int(t['authenticated']) for t in ticks if start<=int(t['utc_ns'])<=end]
server_rows=[json.loads(x) for x in (P/'extracted/game/server.ndjson').read_text().splitlines()]
out['ticks']={'retained_count':len(ticks),'active_count':len(work),'authenticated_peak':max(int(t['authenticated']) for t in ticks),'alive_peak':max(int(t['alive']) for t in ticks),'authenticated_at_last_active_tick':players[-1],'mean_work_ms':statistics.mean(work),'max_work_ms':max(work),'work_over_33_333ms_count':sum(x>1000/30 for x in work),'max_accumulator_lag_s':max(lag),'max_pending_replication':max(int(t['pending_replication']) for t in ticks),'max_deferred_wait_ticks':max(int(t['max_deferred_wait_ticks']) for t in ticks),'observer_mean_us':statistics.mean(int(t['observer_ns']) for t in ticks)/1000,'observer_max_us':max(int(t['observer_ns']) for t in ticks)/1000}
out['server_final_cumulative']={k:server_rows[-1][k] for k in ('decode_errors','send_errors','baselines','deltas')}
out['hashes']={name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ('game.tar.gz','bots.tar.gz','udp_profile.executed.py','udp_profile_record.executed.py','manifest.json','cleanup.json','preserved-measurement-sha256.txt')}
(P/'analysis.json').write_text(json.dumps(out,indent=2)+'\n')

# Perf uses host-local CLOCK_MONOTONIC; translate using measured clock anchors.
from collections import Counter


def parse_profile(directory):
    status = json.loads((directory / 'profile-status.json').read_text())
    anchors = [json.loads(line) for line in (directory / 'profile-clock.ndjson').read_text().splitlines()]
    offsets = [r['utc_ns'] - r['monotonic_ns'] for r in anchors]
    offset = int(statistics.median(offsets))
    samples = []
    for block in (directory / 'perf-script.txt').read_text().split('\n\n'):
        lines = block.splitlines()
        if not lines:
            continue
        header = re.search(r'\s+(\d+)/(\d+)\s+(\d+)\.(\d+):\s+(\d+)\s+cpu-clock:', lines[0])
        if not header:
            raise ValueError('Unparsed perf sample header')
        frames = []
        for line in lines[1:]:
            frame = re.match(r'\s+[0-9a-f]+\s+(.+)\s+\(([^()]*)\)$', line)
            if not frame:
                raise ValueError('Unparsed perf frame')
            symbol = re.sub(r'::h[0-9a-f]{16}$', '', frame[1])
            frames.append((symbol, pathlib.PurePosixPath(frame[2]).name))
        mono = int(header[3]) * 10**9 + int(header[4].ljust(9, '0'))
        samples.append(dict(pid=int(header[1]), tid=int(header[2]), mono_ns=mono,
                            utc_ns=mono+offset, period_ns=int(header[5]), frames=frames))
    loss = Counter({event: 0 for event in ('PERF_RECORD_LOST', 'PERF_RECORD_LOST_SAMPLES',
                                         'PERF_RECORD_THROTTLE', 'PERF_RECORD_UNTHROTTLE',
                                         'PERF_RECORD_SAMPLE')})
    with gzip.open(directory / 'perf-records.txt.gz', 'rt') as stream:
        for line in stream:
            for event in loss:
                if re.search(r'\b' + event + r'\b', line):
                    loss[event] += 1
    assert loss['PERF_RECORD_SAMPLE'] == len(samples)
    measured = [r for r in anchors if r.get('target_stat')]
    def cpu(row):
        fields = row['target_stat'].rsplit(')', 1)[1].split()
        return int(fields[11]) + int(fields[12])
    cpu_seconds = (cpu(measured[-1]) - cpu(measured[0])) / 100
    rate_samples = [s for s in samples if measured[0]['monotonic_ns'] <= s['mono_ns'] <= measured[-1]['monotonic_ns']]
    return samples, dict(status=status, clock_offset_median_ns=offset,
                         clock_offset_spread_ns=max(offsets)-min(offsets),
                         loss_record_counts=dict(loss),
                         sampled_target_cpu_s=cpu_seconds,
                         rate_window_samples=len(rate_samples),
                         effective_samples_per_target_cpu_s=len(rate_samples)/cpu_seconds if cpu_seconds else None,
                         effective_samples_per_wall_s=len(rate_samples)/((measured[-1]['monotonic_ns']-measured[0]['monotonic_ns'])/1e9),
                         sample_count=len(samples),
                         sampled_period_cpu_s=sum(s['period_ns'] for s in samples)/1e9,
                         first_sample_utc_ns=min(s['utc_ns'] for s in samples),
                         last_sample_utc_ns=max(s['utc_ns'] for s in samples))


def summarize_samples(samples, low, high):
    rows = [s for s in samples if low <= s['utc_ns'] < high]
    weight = sum(s['period_ns'] for s in rows)
    leaf, inclusive, stacks, categories = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        frames, period = row['frames'], row['period_ns']
        if frames:
            leaf[frames[0][0]] += period
            stacks[' ← '.join(f[0] for f in frames[:6])] += period
        for symbol in {f[0] for f in frames}:
            inclusive[symbol] += period
        names = '\n'.join(f[0] for f in frames)
        # Categories overlap; these are inclusive observations, not exclusive costs.
        for category, pattern in {
            'enet_transport': r'rusty_enet|enet_',
            'replication': r'broadcast|replication|snapshot|delta_state',
            'simulation': r'world::.*step|world::.*tick|sim_core|combat|monster|projectile',
            'logging': r'tracing_subscriber|tracing_core|tracing::|fmt::format|std::io::stdio|journal',
            'measurement': r'measurement|measure::|serde_json',
            'kernel_network': r'udp_|ip_|sock_|skb_|net_rx|net_tx|__sys_send|__sys_recv',
            'generator': r'omega_load_test',
        }.items():
            if re.search(pattern, names, re.I):
                categories[category] += period
    def top(counter, n=20):
        return [{'symbol': symbol, 'period_ns': amount, 'percent': amount/weight*100}
                for symbol, amount in counter.most_common(n)] if weight else []
    return dict(start_ns=low, end_ns=high, sample_count=len(rows), weighted_cpu_s=weight/1e9,
                frames_at_least_two=sum(len(r['frames']) >= 2 for r in rows),
                samples_with_named_leaf=sum(bool(r['frames']) and r['frames'][0][0] != '[unknown]' for r in rows),
                samples_with_unknown_frame=sum(any(f[0] == '[unknown]' for f in r['frames']) for r in rows),
                samples_reaching_application_main=sum(any(f[0] in ('omega_server::main', 'omega_load_test::main') for f in r['frames']) for r in rows),
                depth_median=statistics.median(len(r['frames']) for r in rows) if rows else None,
                top_self=top(leaf), top_inclusive=top(inclusive), top_stacks=top(stacks, 10),
                overlapping_categories=top(categories),
                selected_symbols={name: {'self_percent': leaf[name]/weight*100 if weight else None,
                                          'inclusive_percent': inclusive[name]/weight*100 if weight else None,
                                          'self_period_ns': leaf[name], 'inclusive_period_ns': inclusive[name]}
                                  for name in ('rusty_enet::c::protocol::enet_protocol_remove_sent_reliable_command',
                                               'omega_server::net::broadcast::BroadcastService::broadcast_state_updates',
                                               'rusty_enet::c::protocol::enet_host_service',
                                               'omega_load_test::bot::Bot::poll',
                                               'omega_load_test::behavior::BehaviorState::decide')})


profile_summary = {}
onset = out['hosts']['game']['first_host_receive_error']
for role in ('game', 'bots'):
    samples, info = parse_profile(P/'extracted'/role)
    windows = {'all': (0, 2**63), 'workload': (start, end), 'last_10s': (end-10*10**9, end)}
    if onset:
        windows.update(before_game_onset_10s=(max(start,onset['start_ns']-10*10**9),onset['start_ns']),
                       after_game_onset_10s=(onset['end_ns'],min(end,onset['end_ns']+10*10**9)),
                       before_game_onset=(start,onset['start_ns']),
                       after_game_onset=(onset['end_ns'],end))
    own = out['hosts'][role]['first_host_receive_error']
    if own and role == 'bots':
        windows.update(before_bot_onset_10s=(max(start,own['start_ns']-10*10**9),own['start_ns']),
                       after_bot_onset=(own['end_ns'],end))
    info['windows'] = {name:summarize_samples(samples,*bounds) for name,bounds in windows.items()}
    info['per_second'] = [summarize_samples(samples,start+i*10**9,min(end,start+(i+1)*10**9))
                          for i in range(int((end-start)/1e9)+1)]
    profile_summary[role] = info
(P/'profile-analysis.json').write_text(json.dumps(profile_summary,indent=2)+'\n')
public = {
    'namespace': 'udp-profile-20261021', 'workload_runs': 1,
    'classification': 'failed-ramp-diagnostic-only', 'new_validated_capacity': None,
    'pinned_binary_sha256': manifest['pinned'],
    'workload': {k: manifest[k] for k in ('requested_bots', 'behavior', 'input_hz', 'seed',
                                         'stagger_ms', 'difficulty', 'ramp_limit_s', 'steady_limit_s')},
    'started_utc_ns': start, 'ended_utc_ns': end, 'elapsed_s': guard['elapsed_s'],
    'remote_guard': guard['reason']['kind'], 'controller_abort': manifest.get('controller_abort'),
    'phase2_reached': False, 'ramp_input_cadence': None, 'generator_valid': None,
    'ticks': out['ticks'], 'hosts': {}, 'profiles': {},
    'tools': json.loads((P/'tools-summary.json').read_text()),
    'cleanup': json.loads((P/'final-verification-summary.json').read_text()),
    'evidence_sha256': out['hashes'],
}
for role in ('game', 'bots'):
    host = out['hosts'][role]
    public['hosts'][role] = {k: host[k] for k in (
        'host_start_ns', 'host_end_ns', 'host_interval_s', 'udp_delta',
        'observed_process_socket_count', 'sum_max_observed_socket_drops',
        'effective_rb_values', 'effective_tb_values', 'max_sampled_receive_memory',
        'max_sampled_recv_q', 'socket_failures', 'collector_cpu_percent_one_core')}
    onset = host['first_host_receive_error']
    public['hosts'][role]['onset'] = {k:v for k,v in onset.items() if k != 'cpu'} if onset else None
    profile = profile_summary[role]
    public['profiles'][role] = {k:v for k,v in profile.items() if k not in ('status', 'windows', 'per_second')}
    public['profiles'][role]['recording'] = {k:v for k,v in profile['status'].items()
                                             if k not in ('argv', 'enable_ack_hex')}
    public['profiles'][role]['windows'] = {}
    for name in ('workload', 'before_game_onset_10s', 'after_game_onset_10s', 'last_10s'):
        window = profile['windows'][name]
        public['profiles'][role]['windows'][name] = {k:(v[:8] if isinstance(v,list) else v)
                                                     for k,v in window.items() if k != 'top_stacks'}
    public['evidence_sha256'][role+'/perf.data'] = hashlib.sha256((P/'extracted'/role/'perf.data').read_bytes()).hexdigest()
report_dir = ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis'
(report_dir/'profile-summary.json').write_text(json.dumps(public,indent=2)+'\n')
print('Private host, socket, Tick and onset-aligned profile analyses written.')

