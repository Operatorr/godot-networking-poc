#!/usr/bin/env python3
"""Analysis of one receive-buffer comparison; versioned retry semantics and coverage stay explicit."""
import sys,pathlib,json,gzip,csv,re,statistics,hashlib,datetime
ROOT=pathlib.Path.cwd();P=ROOT/'deployment/hetzner/results/udp-buffer-20261021'
sys.path.insert(0,str(ROOT/'scripts/load_campaign'));import cpu_report
manifest=json.loads((P/'manifest.json').read_text());guard=json.loads((P/'extracted/bots/guard-result.json').read_text())
ticks=list(csv.DictReader((P/'extracted/game/ticks.csv').open()))
start=json.loads((P/'extracted/bots/workload-start.json').read_text())['utc_ns'];end=guard['ended_utc_ns'];out={'swarm_start_utc_ns':start,'guard_end_utc_ns':end,'guard_elapsed_s':guard['elapsed_s'],'ramp_input_cadence':None,'generator_valid':None,'phase2_reached':(P/'extracted/bots/phase.json').exists(),'hosts':{}}
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
out['hashes']={name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ('game.tar.gz','bots.tar.gz','udp_buffer.executed.py','staged/udp_control_capture.py','manifest.json','cleanup.json','preserved-measurement-sha256.txt')}
(P/'analysis.json').write_text(json.dumps(out,indent=2)+'\n')

import math

def dist(values):
 values=sorted(v for v in values if v is not None)
 return {'n':len(values), 'min':values[0] if values else None,'median':statistics.median(values) if values else None,'p95':values[math.ceil(.95*len(values))-1] if values else None,'p99':values[math.ceil(.99*len(values))-1] if values else None,'max':values[-1] if values else None}

def timing_diff(a,b):
 return {'count':b['count']-a['count'],'total_ns':b['total_ns']-a['total_ns'],'buckets':[y-x for x,y in zip(a['buckets'],b['buckets'])], 'cumulative_max_ns_at_end':b['max_ns']}

def csvread(path):
 return [{k:int(v) for k,v in r.items()} for r in csv.DictReader(path.read_text().splitlines())]

bots=[json.loads(x) for x in (P/'extracted/bots/bots.ndjson').read_text().splitlines()]
server=[r for r in server_rows if r.get('transport') is not None]
ports={role:csvread(P/'extracted'/role/'input-ports.csv') for role in ('game','bots')}
# Backstepping capture timestamps can flush the same port-second twice.
for role in ports:
 merged={}
 for r in ports[role]:
  key=(r['utc_second'],r['port']);dest=merged.setdefault(key,dict(r,input_commands=0));dest['input_commands']+=r['input_commands']
 ports[role]=list(merged.values())
maps={role:({r['port']:r['bot_id'] for r in csvread(P/'extracted'/role/'port-bot.csv')} if (P/'extracted'/role/'port-bot.csv').exists() else {}) for role in ports}
flow={role:csvread(P/'extracted'/role/'flow-points.csv') for role in ports}
def complete_seconds(path, rows):
 status_path=path/'parser-status.json'; flow_path=path/'flow-summary.json'
 if status_path.exists() and flow_path.exists():
  fs=json.loads(flow_path.read_text());first=fs.get('capture_first_timestamp_ns');last=fs.get('capture_last_timestamp_ns')
  if first is not None and last is not None:return (math.ceil(first/1e9),last//10**9)
 return (min(r['utc_second'] for r in rows)+1,max(r['utc_second'] for r in rows)+1)
coverage={role:complete_seconds(P/'extracted'/role,flow[role]) for role in ports}
bins={}
for role in ports:
 aggregated={}
 for row in csvread(P/'extracted'/role/'flow-bins.csv'):
  stamp=row['utc_10ms']; current=aggregated.setdefault(stamp,{k:0 for k in row})
  for k,v in row.items():
   if k!='utc_10ms':current[k]+=v
  current['utc_10ms']=stamp
 bins[role]=list(aggregated.values())
hosts={role:[json.loads(x) for x in gzip.open(P/'extracted'/role/'host.ndjson.gz','rt')] for role in ports}
onset=out['hosts']['game']['first_host_receive_error']
windows={'before_onset_10s':(max(start,onset['start_ns']-10**10),onset['start_ns']), 'after_onset_10s':(onset['end_ns'],min(end,onset['end_ns']+10**10)), 'last_10s':(end-10**10,end)} if onset else {'workload':(start,end)}
windows['workload']=(start,end)
command_rows=[json.loads(x) for x in (P/'commands.ndjson').read_text().splitlines()]
abort_observed_ns=max(x['utc_ns'] for x in command_rows if x['command'].startswith('tail -1 ')) if manifest.get('controller_abort') else end
windows['pre_abort_last_10s']=(max(start,abort_observed_ns-10**10),abort_observed_ns)
windows['active_until_controller_abort']=(start,abort_observed_ns)
summary={'windows':{}, 'server_transport_last':server[-1]['transport'], 'server_loop_phases_last':server[-1]['loop_phases'], 'timing_bounds_us':server[-1]['timing_bounds_us'], 'bot_samples':len(bots),'ramp_samples':sum(b.get('phase')=='ramp' for b in bots),'ramp_phase_s_all_null':all(b['phase_s'] is None for b in bots if b.get('phase')=='ramp'), 'port_to_bot_mappings':{r:len(m) for r,m in maps.items()}, 'collector':{}, 'generator_valid':None,'causal_observer_slowdown':None}
private_bot_intervals=[]
for name,(a,b) in windows.items():
 w={'requested_start_ns':a,'requested_end_ns':b,'hosts':{},'wire':{}}
 sr=[r for r in server if a<=r['utc_ns']<=b]
 if len(sr)>1:
  f,l=sr[0],sr[-1]
  w['server']={'start_ns':f['utc_ns'],'end_ns':l['utc_ns'],'elapsed_s':(l['utc_ns']-f['utc_ns'])/1e9,'read_gaps':timing_diff(f['transport']['read_gaps'],l['transport']['read_gaps']), 'transport':{k:l['transport'][k]-f['transport'][k] for k in l['transport'] if k!='read_gaps'},'phases':{k:timing_diff(f['loop_phases'][k],l['loop_phases'][k]) for k in l['loop_phases']}}
 br=[r for r in bots if a<=r['utc_ns']<=b]; rates=[];gaps=[0]*8;missed=0; botids=set(); ages={k:[] for k in ('snapshot_age_s','delta_age_s','confirm_age_s')}
 for f,l in zip(br,br[1:]):
  old={v['id']:v for v in f['bots']};dt=(l['utc_ns']-f['utc_ns'])/1e9
  for v in l['bots']:
   for k in ages:
    if v['phase']=='Running':ages[k].append(v[k])
   if v['id'] not in old:continue
   u=old[v['id']]
   if u['phase']!='Running' or v['phase']!='Running':continue
   n=v['inputs']-u['inputs'];d=[y-x for x,y in zip(u['input_gaps'],v['input_gaps'])];m=v['missed_schedules']-u['missed_schedules']
   rates.append(n/dt);botids.add(v['id']);gaps=[x+y for x,y in zip(gaps,d)];missed+=m
   private_bot_intervals.append(dict(window=name,bot_id=v['id'],start_ns=f['utc_ns'],end_ns=l['utc_ns'],inputs=n,input_hz=n/dt,input_gaps=d,missed=m))
 w['bot_scheduler']={'sample_start_ns':br[0]['utc_ns'] if br else None,'sample_end_ns':br[-1]['utc_ns'] if br else None,'playing_bot_ids':len(botids),'per_playing_bot_interval_hz':dist(rates),'input_gap_buckets':gaps,'missed_schedules':missed,'delivery_age_s':{k:dist(v) for k,v in ages.items()}}
 for role in ports:
  h=[r for r in hosts[role] if a<=r['utc_ns']<=b]
  if len(h)>1:
   c,d=counters(h[0]['net/snmp']),counters(h[-1]['net/snmp'])
   w['hosts'][role]={'start_ns':h[0]['utc_ns'],'end_ns':h[-1]['utc_ns'],'udp_delta':{k:d[k]-c[k] for k in c}, 'cpu':cpu_report.interval(h[0],h[-1])}
  # Complete UTC-second and 10ms bins only; absent port-second implies zero only for a mapped, already observed port.
  lo=max(math.ceil(a/1e9),coverage[role][0]);hi=min(int(b//10**9),coverage[role][1])
  fr=[r for r in flow[role] if lo<=r['utc_second']<hi]
  ps=[r for r in ports[role] if lo<=r['utc_second']<hi]
  bs=[r for r in bins[role] if lo*100<=r['utc_10ms']<hi*100]
  w['wire'][role]={'start_utc_second':lo,'end_utc_second':hi,'complete_utc_seconds':max(0,hi-lo),'all_complete_utc_seconds_inside_requested_window_present':hi>=int(b//10**9) and lo<=math.ceil(a/1e9),'observed_port_seconds':len(ps),'input_count_nonzero_port_seconds':dist([r['input_commands'] for r in ps]),'totals':{k:sum(r[k] for r in fr) for k in fr[0] if k!='utc_second'} if fr else {}, 'bins_10ms':{k:dist([r[k] for r in bs]) for k in ('out_packets','in_packets','inputs','retry_command_bytes','out_acks','in_acks')}}
 summary['windows'][name]=w
for role in ports:
 d=P/'extracted'/role
 summary['collector'][role]={'resource':json.loads((d/'capture-resource.json').read_text()),'capture_accounting':(d/'capture.log').read_text().splitlines()[-5:], 'retained_files':{f.name:f.stat().st_size for f in d.iterdir() if f.name in ('datagrams.bin','flow-points.csv','input-ports.csv','port-bot.csv','flow-bins.csv','capture.log','flow-summary.json')},'source_hashes':(d/'collector-sha256.txt').read_text()}
 summary['collector'][role]['flow_summary']=json.loads((d/'flow-summary.json').read_text()) if (d/'flow-summary.json').exists() else None
 summary['collector'][role]['parser_status']=json.loads((d/'parser-status.json').read_text()) if (d/'parser-status.json').exists() else None
 summary['collector'][role]['malformed_packets']=(summary['collector'][role]['parser_status'] or {}).get('parse_errors')
 summary['collector'][role]['first_complete_second']=coverage[role][0]
 summary['collector'][role]['last_complete_second']=coverage[role][1]-1
(P/'timing-cadence-analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
(P/'per-bot-intervals.json').write_text(json.dumps(private_bot_intervals)+'\n')
print('Host/socket/Tick and timing/cadence analyses written privately.')
# Align complete wire seconds with bot identity and Running observations bracketing them.
by_sample=[(r['utc_ns'],{v['id']:v for v in r['bots']}) for r in bots]
aligned=[]
for name,(a,b) in windows.items():
 for sec in range(max(math.ceil(a/1e9),*(v[0] for v in coverage.values())),min(int(b//10**9),*(v[1] for v in coverage.values()))):
  before=[r for r in by_sample if r[0]<=sec*10**9];after=[r for r in by_sample if r[0]>=(sec+1)*10**9]
  if not before or not after:continue
  left,right=before[-1],after[0]
  ids=set(left[1])&set(right[1]);ids={i for i in ids if left[1][i]['phase']==right[1][i]['phase']=='Running'}
  observations={}
  for role in ports:
   observations[role]={maps[role][r['port']]:r['input_commands'] for r in ports[role] if r['utc_second']==sec and r['port'] in maps[role]}
  for i in ids:
   aligned.append({'window':name,'utc_second':sec,'bot_id':i,'bot_wire_inputs':observations['bots'].get(i,0) if i in maps['bots'].values() else None,'game_wire_inputs':observations['game'].get(i,0) if i in maps['game'].values() else None})
for name in windows:
 matched=[r for r in aligned if r['window']==name]
 summary['windows'][name]['aligned_running_bot_wire']=({k:dist([r[k] for r in matched]) for k in ('bot_wire_inputs','game_wire_inputs')} if all(maps.values()) else None)
(P/'per-bot-wire-seconds.json').write_text(json.dumps(aligned)+'\n')
(P/'timing-cadence-analysis.json').write_text(json.dumps(summary,indent=2)+'\n')

# Compare the two observations with identical elapsed-time bins and first-ascent
# population bands. Preserve each source's inner boundaries rather than pretending
# that independently sampled streams have exact common endpoints.
CONTROL=ROOT/'deployment/hetzner/results/udp-bounded-20261021'

def load_run(path):
 d=path/'extracted'
 return {
  'path':path,
  'start':json.loads((d/'bots/workload-start.json').read_text())['utc_ns'],
  'end':json.loads((d/'bots/guard-result.json').read_text())['ended_utc_ns'],
  'ticks':[{k:float(v) if k in ('accumulator_lag_s','budget_pct','mean_x','mean_y','mean_radius_sq') else int(v) for k,v in t.items()} for t in csv.DictReader((d/'game/ticks.csv').open())],
  'server':[r for r in (json.loads(x) for x in (d/'game/server.ndjson').open()) if r.get('transport') is not None],
  'bots':[json.loads(x) for x in (d/'bots/bots.ndjson').open()],
  'hosts':{r:[json.loads(x) for x in gzip.open(d/r/'host.ndjson.gz','rt')] for r in ('game','bots')},
  'flow':{r:csvread(d/r/'flow-points.csv') for r in ('game','bots')},
 }

def matched_window(run,a,b):
 result={'requested_elapsed_s':[(a-run['start'])/1e9,(b-run['start'])/1e9], 'requested_utc_ns':[a,b]}
 ts=[t for t in run['ticks'] if a<=t['utc_ns']<b]
 result['ticks']={k:dist([t[k] for t in ts]) for k in ('authenticated','alive','monsters','projectiles','effects','pending_replication','max_deferred_wait_ticks')}
 result['ticks'].update(count=len(ts),work_ms=dist([t['work_ns']/1e6 for t in ts]),work_over_deadline=sum(t['work_ns']>1e9/30 for t in ts),max_accumulator_lag_s=max((t['accumulator_lag_s'] for t in ts),default=None), observed_ticks_per_requested_second=len(ts)/((b-a)/1e9))
 sr=[r for r in run['server'] if a<=r['utc_ns']<=b]
 if len(sr)>1:
  f,l=sr[0],sr[-1];dt=(l['utc_ns']-f['utc_ns'])/1e9
  result['server']={'inner_utc_ns':[f['utc_ns'],l['utc_ns']], 'elapsed_s':dt,'phases':{k:dict(timing_diff(f['loop_phases'][k],l['loop_phases'][k]),wall_percent=100*(l['loop_phases'][k]['total_ns']-f['loop_phases'][k]['total_ns'])/(dt*1e9)) for k in l['loop_phases']}, 'read_gaps':timing_diff(f['transport']['read_gaps'],l['transport']['read_gaps']), 'transport':{k:l['transport'][k]-f['transport'][k] for k in l['transport'] if k!='read_gaps'}}
 else:result['server']=None
 result['hosts']={}
 for role in ('game','bots'):
  h=[r for r in run['hosts'][role] if a<=r['utc_ns']<=b]
  if len(h)>1:
   c,d=counters(h[0]['net/snmp']),counters(h[-1]['net/snmp']);result['hosts'][role]={'inner_utc_ns':[h[0]['utc_ns'],h[-1]['utc_ns']],'cpu':cpu_report.interval(h[0],h[-1]),'udp_delta':{k:d[k]-c[k] for k in c}}
  else:result['hosts'][role]=None
  if h:
   observed=[sock for row in h for sock in sockets(row['ss']['stdout'])]
   if result['hosts'][role] is not None:
    result['hosts'][role]['receive_memory_bytes']=dist([sock['r'] for sock in observed])
    result['hosts'][role]['effective_receive_buffers']=sorted({sock['rb'] for sock in observed})
    result['hosts'][role]['socket_observation_utc_ns']=[h[0]['socket_before_utc_ns'],h[-1]['socket_after_utc_ns']]
 br=[r for r in run['bots'] if a<=r['utc_ns']<=b];rates=[];offered={k:0 for k in ('inputs','shoot_inputs','ability_inputs','missed_schedules','baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')};peer_seconds=0;ages={k:[] for k in ('snapshot_age_s','confirm_age_s')};visible=[]
 for f,l in zip(br,br[1:]):
  old={v['id']:v for v in f['bots']};dt=(l['utc_ns']-f['utc_ns'])/1e9
  for v in l['bots']:
   if v['phase']=='Running':
    for k in ages:ages[k].append(v[k])
    visible.append(v['visible_entities'])
   u=old.get(v['id'])
   if not u or u['phase']!='Running' or v['phase']!='Running':continue
   peer_seconds+=dt;rates.append((v['inputs']-u['inputs'])/dt)
   for k in offered:offered[k]+=v[k]-u[k]
 result['bots']={'inner_utc_ns':[br[0]['utc_ns'],br[-1]['utc_ns']] if br else None,'running_peer_seconds':peer_seconds,'per_peer_interval_hz':dist(rates),'offered_and_error_deltas':offered if rates else None,'visible_entities':dist(visible),'delivery_age_s':{k:dist(v) for k,v in ages.items()}}
 result['wire']={}
 for role in ('game','bots'):
  rows=run['flow'][role];first,last=complete_seconds(run['path']/'extracted'/role,rows);lo=max(math.ceil(a/1e9),first);hi=min(int(b//10**9),last)
  rows=[r for r in rows if lo<=r['utc_second']<hi]
  result['wire'][role]={'complete_utc_seconds':max(0,hi-lo),'inner_utc_seconds':[lo,hi] if rows else None,'all_complete_utc_seconds_inside_requested_window_present':lo<=math.ceil(a/1e9) and hi>=int(b//10**9),'totals':{k:sum(r[k] for r in rows) for k in rows[0] if k!='utc_second'} if rows else None}
 return result

runs={'bounded_collector':load_run(CONTROL),'receive_buffer':load_run(P)}
comparison={'semantics':'Receive-buffer intervention plus mapping-only instrumentation correction. Both readers use v2 sequence-window retries without TTL; only name extraction differs. Single observations with entropy-seeded Worlds. Bins condition on time/population, not equal entity layout. Inner timestamp boundaries and actual offered/entity load are retained. No causal confidence intervals or capacity claim. Maxima remain cumulative. Empty wire tails are null.','elapsed_time_bins':{},'first_ascent_population_bands':{}}
for lo,hi in ((0,10),(10,15),(15,20),(20,25),(25,30),(30,35),(35,40)):
 comparison['elapsed_time_bins'][f'{lo}-{hi}s']={name:(matched_window(r,r['start']+lo*10**9,r['start']+hi*10**9) if r['end']>=r['start']+hi*10**9 else None) for name,r in runs.items()}
for lo,hi in ((100,125),(125,150),(150,175),(175,200)):
 group={}
 for name,r in runs.items():
  entered=next((i for i,t in enumerate(r['ticks']) if t['utc_ns']>=r['start'] and lo<=t['authenticated']<hi),None)
  if entered is None:group[name]=None;continue
  departed=next((i for i in range(entered+1,len(r['ticks'])) if not lo<=r['ticks'][i]['authenticated']<hi),None)
  if departed is None:group[name]=None;continue
  a=r['ticks'][entered]['utc_ns'];b=r['ticks'][departed]['utc_ns'];group[name]=matched_window(r,a,b)
 comparison['first_ascent_population_bands'][f'{lo}-{hi-1}']=group
(P/'matched-comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
print('Matched elapsed-time and actual-population comparisons written privately.')

# Validate the reader independently of capture EOF and of the workload outcome.
validation={}
for role in ('game','bots'):
 d=P/'extracted'/role
 ps=json.loads((d/'parser-status.json').read_text()) if (d/'parser-status.json').exists() else None
 fs=json.loads((d/'flow-summary.json').read_text()) if (d/'flow-summary.json').exists() else None
 log=(d/'capture.log').read_text()
 def number(pattern):
  hit=re.search(pattern,log);return int(hit[1]) if hit else None
 captured=number(r'(\d+) packets captured');received=number(r'(\d+) packets received by filter');dropped=number(r'(\d+) packets dropped by kernel')
 mapping_rows=csvread(d/'port-bot.csv')
 mapping_pairs={(r['port'],r['bot_id']) for r in mapping_rows}
 port_ambiguity=[p for p in {r['port'] for r in mapping_rows} if len({r['bot_id'] for r in mapping_rows if r['port']==p})>1]
 id_ambiguity=[i for i in {r['bot_id'] for r in mapping_rows} if len({r['port'] for r in mapping_rows if r['bot_id']==i})>1]
 running_ids={v['id'] for row in bots for v in row['bots'] if v['phase']=='Running'}
 offering_ids={v['id'] for row in bots for v in row['bots'] if v['inputs']>0}
 observed_ports={r['port'] for r in ports[role]}
 raw_points=csvread(d/'flow-points.csv')
 aggregated_points={}
 for row in raw_points:
  sec=row['utc_second'];dest=aggregated_points.setdefault(sec,{k:0 for k in row if k!='utc_second'})
  for k in dest:dest[k]+=row[k]
 validation[role]={
  'parser_status':ps,'capture_packets':captured,'capture_filter_received':received,'capture_kernel_dropped':dropped,
  'reader_packets_equal_tcpdump_captured':ps['packets']==captured if ps and captured is not None else None,
  'filter_received_minus_captured':received-captured if received is not None and captured is not None else None,
  'complete_seconds_cover_to_swarm_stop':coverage[role][1]>=int(end//10**9),
  'complete_seconds_cover_to_controller_abort':coverage[role][1]>=int(abort_observed_ns//10**9),
  'reader_exit_code':summary['collector'][role]['resource']['exit_code'],
  'flow_format':fs.get('format') if fs else None,'retry_semantics':fs.get('retry_semantics') if fs else None,
  'unclassified_reliable_all_capture':fs.get('unclassified_reliable_all_capture') if fs else None,
  'reliable_streams':fs.get('reliable_streams') if fs else None,'reliable_history_bytes':fs.get('reliable_history_bytes') if fs else None,
  'first_packet_elapsed_s':(fs['capture_first_timestamp_ns']-start)/1e9 if fs else None,
  'last_packet_elapsed_s':(fs['capture_last_timestamp_ns']-start)/1e9 if fs else None,
  'packet_end_relative_to_guard_s':(fs['capture_last_timestamp_ns']-end)/1e9 if fs else None,
  'timestamp_backstep_ns':fs.get('max_timestamp_backstep_ns') if fs else None,
  'parser_last_equals_flow_last':ps['last_read_record_utc_ns']==fs['capture_last_timestamp_ns'] if ps and fs else None,
  'mapping_rows':len(mapping_rows),'mapping_pairs':len(mapping_pairs),'ports_mapped':len(maps[role]),'ids_mapped':len(set(maps[role].values())),
  'port_reuse_conflicts':port_ambiguity,'bot_ids_with_multiple_ports':id_ambiguity,
  'running_ids_unmapped':sorted(running_ids-set(maps[role].values())), 'offering_ids_unmapped':sorted(offering_ids-set(maps[role].values())),
  'observed_input_ports_unmapped':sorted(observed_ports-set(maps[role])),
  'whole_capture_input_commands_from_port_rows':sum(r['input_commands'] for r in ports[role]),
  'whole_capture_input_commands_from_summary':sum(fs['wire_input_counts_by_port'].values()) if fs else None,
  'complete_utc_seconds_range_exclusive':list(coverage[role]),
  'complete_seconds_observed':len({r['utc_second'] for r in raw_points if coverage[role][0]<=r['utc_second']<coverage[role][1]}),
  'flow_point_duplicate_seconds':len(raw_points)-len(aggregated_points),
  'retained_parser_status_bytes':(d/'parser-status.json').stat().st_size if ps else None,
  'sequence_assumptions_empirically_proven':False,
 }
 validation[role]['valid_captured_prefix']=bool(ps and ps['status']=='eof' and ps['parse_errors']==0 and ps['packets']==captured and dropped==0 and validation[role]['reader_exit_code']==0 and not port_ambiguity)
validation['cross_host_mapping_equal']=maps['game']==maps['bots'] if all(maps.values()) else None
validation['identity_mapping_complete']=all(bool(maps[r]) and not validation[r]['offering_ids_unmapped'] and not validation[r]['observed_input_ports_unmapped'] for r in ('game','bots'))
validation['all_requested_collector_requirements_met']=validation['identity_mapping_complete'] and validation['cross_host_mapping_equal'] and all(not validation[r]['bot_ids_with_multiple_ports'] and validation[r]['valid_captured_prefix'] for r in ('game','bots'))
validation['identity_and_retained_prefix_valid']=validation['all_requested_collector_requirements_met']
validation['full_swarm_window_covered']=all(validation[r]['complete_seconds_cover_to_swarm_stop'] for r in ('game','bots'))
validation['all_requested_collector_requirements_met']=validation['all_requested_collector_requirements_met'] and validation['full_swarm_window_covered']
(P/'collector-validation.json').write_text(json.dumps(validation,indent=2)+'\n')

latest={}
for row in bots:
 for bot in row['bots']:latest[bot['id']]=bot
bot_observations={
 'samples':len(bots),'ramp_samples':sum(r.get('phase')=='ramp' for r in bots),
 'ramp_phase_s_all_null':all(r['phase_s'] is None for r in bots if r.get('phase')=='ramp'),
 'last_sample_utc_ns':bots[-1]['utc_ns'],'observed_identities':len(latest),
 'observed_running_identities':len({v['id'] for row in bots for v in row['bots'] if v['phase']=='Running'}),
 'last_sample_phases':{k:sum(v['phase']==k for v in bots[-1]['bots']) for k in sorted({v['phase'] for v in bots[-1]['bots']})},
 'cumulative':{k:sum(v[k] for v in latest.values()) for k in ('inputs','shoot_inputs','ability_inputs','missed_schedules','baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')},
 'max_input_gap_ms':max(v['input_gap_max_ms'] for row in bots for v in row['bots']),
 'input_gap_buckets':[sum(v['input_gaps'][i] for v in latest.values()) for i in range(8)],
 'input_gap_bounds_ms':bots[-1]['gap_bounds_ms'],
 'completed_observer_ns':bots[-1]['completed_observer_ns'],'completed_samples':bots[-1]['completed_samples'],
}
(P/'bot-observations.json').write_text(json.dumps(bot_observations,indent=2)+'\n')
print('Collector validity and final bot observations written privately.')


# Live mappings were read independently on each host. Compare only IDs already
# observed before both reads; asynchronous join prefixes need not have equal size.
live=[]
for row in (json.loads(x) for x in (P/'live-mappings.ndjson').read_text().splitlines()):
 parsed={r:[{k:int(v) for k,v in x.items()} for x in csv.DictReader(row['maps'][r].splitlines())] for r in ('game','bots')}
 lm={r:{x['port']:x['bot_id'] for x in parsed[r]} for r in parsed}
 earliest=min(v[0] for v in row['read_windows_ns'].values())
 prior=[r for r in bots if r['utc_ns']<=earliest]
 offering={v['id'] for r in prior for v in r['bots'] if v['inputs']>0}
 common=set(lm['game'])&set(lm['bots'])
 live.append({'elapsed_s':(row['utc_ns']-start)/1e9,'read_windows_ns':row['read_windows_ns'],
   'already_observed_offering_ids':len(offering), 'mapping_counts':{r:len(lm[r]) for r in lm},
   'unmapped_previously_offering_counts':{r:len(offering-set(lm[r].values())) for r in lm},
   'common_port_disagreements':sum(lm['game'][p]!=lm['bots'][p] for p in common),
   'unique_both_directions':{r:len(lm[r])==len(set(lm[r].values()))==len(parsed[r]) for r in lm}})
identity_wire={
 'live_checkpoints':live,
 'all_live_previously_offering_ids_mapped':bool(live) and all(all(v==0 for v in x['unmapped_previously_offering_counts'].values()) for x in live),
 'all_live_common_mappings_agree':bool(live) and all(x['common_port_disagreements']==0 for x in live),
 'live_poll_ssh_wall_ms':dist([(b-a)/1e6 for x in live for a,b in x['read_windows_ns'].values()]),
 'active_second_definition':'Complete UTC seconds with Running observations bracketing the entire second; absent mapped input-port rows become zero, only inside complete capture coverage.',
 'per_identity':{},
 'application_delivered_inputs':None,
}
for bot_id in sorted({r['bot_id'] for r in aligned if r['window']=='workload'}):
 ar=[r for r in aligned if r['window']=='workload' and r['bot_id']==bot_id]
 oi=[r for r in private_bot_intervals if r['window']=='workload' and r['bot_id']==bot_id]
 identity_wire['per_identity'][str(bot_id)]={'active_complete_seconds':len(ar),
  'offered_interval_hz':dist([r['input_hz'] for r in oi]),
  'wire_input_commands_per_second':{r:dist([v[r+'_wire_inputs'] for v in ar]) for r in ('game','bot')},
  'zero_wire_seconds':{r:sum(v[r+'_wire_inputs']==0 for v in ar) for r in ('game','bot')},
  'cross_host_second_count_mismatches':sum(v['bot_wire_inputs']!=v['game_wire_inputs'] for v in ar)}
(P/'identity-wire-validation.json').write_text(json.dumps(identity_wire,indent=2)+'\n')

# Joint time/population/entity conditioning. Each row is a contiguous source
# segment, never a sum pretending discontinuous selected samples are one window.
comparison['joint_population_entity_segments']={}
for lo,hi in ((10,15),(15,20),(20,25),(25,30),(30,35),(35,40)):
 groups={}
 for name,r in runs.items():
  for t in r['ticks']:
   elapsed=(t['utc_ns']-r['start'])/1e9
   if not lo<=elapsed<hi:continue
   key=(t['authenticated']//25*25,t['alive']//25*25,t['projectiles']//50*50,t['monsters'],t['effects'])
   groups.setdefault(key,{}).setdefault(name,[]).append(t)
 common={}
 for key,byrun in groups.items():
  if len(byrun)!=2:continue
  segments={}
  for name,ts in byrun.items():
   r=runs[name];all_ticks=r['ticks'];index={t['utc_ns']:i for i,t in enumerate(all_ticks)}
   chunks=[];chunk=[];previous=None
   for t in ts:
    idx=index[t['utc_ns']]
    if previous is not None and idx!=previous+1:
     chunks.append(chunk);chunk=[]
    chunk.append(t);previous=idx
   if chunk:chunks.append(chunk)
   segments[name]=[]
   for chunk in chunks:
    a=chunk[0]['utc_ns'];i=index[chunk[-1]['utc_ns']]+1
    b=min(all_ticks[i]['utc_ns'] if i<len(all_ticks) else r['end'],r['start']+hi*10**9,r['end'])
    if b>a:segments[name].append(matched_window(r,a,b))
  common[str(key)]={'bands':{'authenticated':[key[0],key[0]+24],'alive':[key[1],key[1]+24],'projectiles':[key[2],key[2]+49],'monsters':key[3],'effects':key[4]},'sources':segments}
 comparison['joint_population_entity_segments'][f'{lo}-{hi}s']=common
(P/'matched-comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')

ansi=re.compile(r'\x1b\[[0-9;]*m')
game_log=ansi.sub('',(P/'workload-game.log').read_text())
oversized=[line for line in game_log.splitlines() if 'oversized unreliable packet' in line]
limits={
 'new_validated_capacity':None,'generator_valid':None,'causal_instrumentation_performance_effect':None,
 'per_command_queue_residence':None,'server_received_per_bot_input_cadence':None,
 'outstanding_reliable_queue':None,'full_run_oversized_warning_count':None,
 'retained_game_log_lines':len(game_log.splitlines()),'retained_oversized_unreliable_warnings':len(oversized),
 'oversized_payload_bytes':dist([int(re.search(r'packet \((\d+) B\)',line)[1]) for line in oversized]),
 'bot_host_unattributed_receive_errors':out['hosts']['bots']['udp_delta']['RcvbufErrors']-out['hosts']['bots']['sum_max_observed_socket_drops'],
 'world_seed':'Entropy-seeded World; bot seed 30 does not fix entity trajectories.',
 'perfect_single_factor_equivalence':False,
 'pre_swarm_instrumentation_panic':True,
 'captured_invocation_mismatch_recovered':True,
 'runtime_proc_hash_directly_measured_after_restart':False,
 'instrumentation_difference':'994cce8 includes actual-encoder ConnectAuth character_id/name offset fix from 227a9ec and parser-equivalent Clippy cleanup. Mapping only; unchanged sequence/retry/input/ACK/fingerprint semantics relative to 30ec792. Live controller map polling also has measured SSH wall cost, not isolated causal slowdown.',
 'sequence_assumptions':'No unseen data-command advance >=32768 and no port reuse; compact capture cannot prove these. ACKs do not advance history. Half-range observations remain unclassified.',
 'wire_semantics':'Interface capture precedes socket drops. Identity-aligned wire counts are not application-delivered inputs; cross-host UTC-second count mismatches are not loss estimates.',
 'read_gap_semantics':'Time between receive attempts, including sleep; not queue residence.',
 'delivery_age_semantics':'Application-observed time since last message; not one-way latency or queue residence.',
 'capture_eof_semantics':'Game capture stops before swarm termination during cleanup; filter-received minus captured records unconsumed capture-tail accounting, not zero total capture loss. EOF is pipe completion, checked separately against packet counts, timestamps, malformed packets and capture loss. Zero malformed packets is not zero application loss.',
 'bin_semantics':'Duplicate timestamps merged. Empty 10ms bins are absent; distributions condition on traffic bins. Active mapped input port-seconds explicitly include zeros.',
}
for role in ('game','bots'):
 v=validation[role]
 v['observed_input_port_count']=len({r['port'] for r in ports[role]})
 v['observed_input_ports_unmapped_count']=len(v.pop('observed_input_ports_unmapped'))
 v['port_reuse_conflicts_count']=len(v.pop('port_reuse_conflicts'))
 c=summary['collector'][role]
 c['resource']['children_cpu_percent_one_core_over_capture_lifetime']=100*c['resource']['children_cpu_s']/c['resource']['elapsed_s']
 c['resource']['supervisor_cpu_percent_one_core_over_capture_lifetime']=100*c['resource']['self_cpu_s']/c['resource']['elapsed_s']
 c['resource']['rss_semantics']='Maximum waited-for child RSS; not summed cgroup or isolated reader RSS.'
 c.pop('source_hashes',None)
 if c['flow_summary']:c['flow_summary']['wire_input_port_count']=len(c['flow_summary'].pop('wire_input_counts_by_port'))
old=json.loads((ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis/bounded-collector-summary.json').read_text())
reason=guard.get('reason') or {}
public={
 'namespace':manifest['namespace'],'workload_runs':manifest['workloads_launched'],
 'classification':'failed-population-diagnostic-only; '+str(manifest.get('controller_abort') or reason.get('kind')),
 'new_validated_capacity':None,'generator_valid':None,
 'intervention':manifest['intervention'],'comparison_namespace':'udp-bounded-20261021',
 'candidate_revision':manifest['candidate_revision'],'bot_revision':'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb','collector_revision':manifest['collector_revision'],
 'binary_sha256':manifest['experiment_binary_sha256'],'runtime_game_sha256':None,'initial_preflight_proc_exe_sha256':manifest['running_game_executable_sha256'],'runtime_restart_proof':json.loads((P/'runtime-restart-proof.json').read_text()),
 'runtime_bot_sha256':json.loads((P/'extracted/bots/workload-start.json').read_text())['runtime_sha256'],
 'preserved_binary_sha256':manifest['pinned'],'preserved_control_sha256':manifest['control_binary_sha256'],
 'preserved_bitmap_sha256':'29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421',
 'build':json.loads((P/'build-proof.json').read_text()),
 'config_proof':manifest['config_proof'],
 'workload':{k:manifest[k] for k in ('requested_bots','behavior','ramp_limit_s','steady_limit_s','input_hz','seed','stagger_ms','difficulty','game_config','abort_policy')},
 'commands':{
  'controller':'python3 scripts/load_campaign/udp_buffer.py run',
  'build':'source /home/deploy/.cargo/env; cd /home/deploy/omega-udp-buffer-f1cc5d6/rust; cargo build --release --locked -p omega-server',
  'collector_freeze':'git show 994cce8c7cb2f689cd59f4d09e93e270057aba7e:scripts/load_campaign/<source>',
  'collector_compile':'source /home/deploy/.cargo/env; rustc --edition=2021 -O /home/deploy/omega-results/udp-buffer-20261021/udp_control_record.rs -o /home/deploy/omega-results/udp-buffer-20261021/flow-record',
  'bot':manifest['command'].replace(__import__('run').HOSTS['game']['ipv4'],'<game-host>'),
  'game':'OMEGA_MEASURE_DIR=/home/deploy/omega-results/udp-buffer-20261021/game /home/deploy/omega-udp-buffer-f1cc5d6/rust/target/release/omega-server --config /home/deploy/omega-results/udp-buffer-20261021/arena-buffer.json --allow-unsigned-tickets',
  'analysis':'python3 scripts/load_campaign/udp_buffer_analysis.py',
  'verify':'python3 scripts/load_campaign/udp_buffer.py verify'},
 'start_utc_ns':start,'end_utc_ns':end,'controller_abort_observed_at_ns':abort_observed_ns,'controller_abort_elapsed_s':(abort_observed_ns-start)/1e9,'guard_elapsed_s':guard['elapsed_s'],'guard_kind':reason.get('kind'),
 'guard_line':ansi.sub('',reason.get('line','')),'controller_abort':manifest.get('controller_abort'),'phase2_reached':out['phase2_reached'],
 'ticks':out['ticks'],'server_final_cumulative':out['server_final_cumulative'],
 'server_transport_last':summary['server_transport_last'],'server_loop_phases_last':summary['server_loop_phases_last'],'timing_bounds_us':summary['timing_bounds_us'],
 'hosts':out['hosts'],'windows':summary['windows'],'matched_comparison':comparison,
 'bot_observations':bot_observations,'collector':summary['collector'],'collector_validation':validation,
 'identity_wire_validation':identity_wire,
 'collector_sources_sha256':manifest['collector_source_sha256'],'controller_sha256':manifest['controller_sha256'],
 'post_journal_audit':json.loads((P/'post-journal-audit.json').read_text()),'supplement_verification':json.loads((P/'supplement-verification.json').read_text()),'limits':limits,'cleanup':json.loads((P/'cleanup.json').read_text()),'final_verification':json.loads((P/'final-verification-summary.json').read_text()),
 'onset_server_observations':[{k:r[k] for k in ('utc_ns','transport','loop_phases')} for r in server if onset and onset['start_ns']-2e9<=r['utc_ns']<=onset['end_ns']+2e9],
 'observer_comparison':{r:{'bounded_control_resource':old['collector'][r]['resource'],'candidate_resource':summary['collector'][r]['resource'],'equal_observation_windows':False} for r in ('game','bots')},
 'preflight':{r:{'available_disk_bytes':int(json.loads((P/(r+'-before.json')).read_text())['disk'])} for r in ('game','bots')},
 'collection_limits':{'capture_s':300,'retained_guard_bytes':48*1024**2,'file_limit_bytes':64*1024**2,'cgroup_memory_bytes':512*1024**2,'fingerprint_modulus':64,'host_socket_cadence_s':1,'flow_port_cadence_s':1,'burst_bin_ms':10,'swarm_runtime_s':305,'restoration_s':420,'host_collector_runtime_s':350,'capture_unit_runtime_s':310,'join_guard_cadence_s':0.5,'controller_poll_sleep_s':2,'game_log_tail_lines':4000,'bot_log_size_guard_bytes':8*1024**2},
}
public['evidence_sha256']={name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ('game.tar.gz','bots.tar.gz','manifest.json','cleanup.json','preserved-measurement-sha256.txt','udp_buffer.executed.py','game-final-verification.json','bots-final-verification.json','final-verification-summary.json','matched-comparison.json','timing-cadence-analysis.json','analysis.json','collector-validation.json','bot-observations.json','identity-wire-validation.json','commands.ndjson','game-before.json','bots-before.json','game-after.json','bots-after.json','build-identity.txt','build-proof.json','build-command.txt','build.log','build-environment-audit.json','candidate-rust.diff','live-mappings.ndjson','config-proof.json','runtime-restart-proof.json','supplement-verification.json','game-journal-supplement.tar.gz','workload-game.log','startup-invocations.jsonl','journal-invocations.jsonl','post-journal-audit.json','game-post-journal-audit.txt','bots-post-journal-audit.txt')}
public['collector_executable_sha256']={r:next(line.split()[0] for line in (P/'extracted'/r/'collector-sha256.txt').read_text().splitlines() if line.endswith('/flow-record')) for r in ('game','bots')}
public['analysis_source_sha256']=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
destination=ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis/receive-buffer-summary.json'
encoded=json.dumps(public,indent=2)+'\n'
for host in __import__('run').HOSTS.values():assert host['ipv4'] not in encoded, 'Private address in public summary'
destination.write_text(encoded)
print('Receive-buffer summary written; private-address scan passed.')
