#!/usr/bin/env python3
"""Private analysis of the single instrumented control; partial wire coverage stays explicit."""
import sys,pathlib,json,gzip,csv,re,statistics,hashlib,datetime
ROOT=pathlib.Path.cwd();P=ROOT/'deployment/hetzner/results/udp-control-20261021'
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
out['hashes']={name:hashlib.sha256((P/name).read_bytes()).hexdigest() for name in ('game.tar.gz','bots.tar.gz','udp_control.executed.py','udp_control_capture.executed.py','manifest.json','cleanup.json','preserved-measurement-sha256.txt')}
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
maps={role:({r['port']:r['bot_id'] for r in csvread(P/'extracted'/role/'port-bot.csv')} if (P/'extracted'/role/'port-bot.csv').exists() else {}) for role in ports}
flow={role:csvread(P/'extracted'/role/'flow-points.csv') for role in ports}
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
  lo=max(math.ceil(a/1e9), min(r['utc_second'] for r in flow[role])+1);hi=min(int(b//10**9),max(r['utc_second'] for r in flow[role])+1)
  fr=[r for r in flow[role] if lo<=r['utc_second']<hi]
  ps=[r for r in ports[role] if lo<=r['utc_second']<hi]
  bs=[r for r in bins[role] if lo*100<=r['utc_10ms']<hi*100]
  w['wire'][role]={'start_utc_second':lo,'end_utc_second':hi,'complete_utc_seconds':max(0,hi-lo),'coverage_complete_for_requested_window':hi>=int(b//10**9) and lo<=math.ceil(a/1e9),'observed_port_seconds':len(ps),'input_count_nonzero_port_seconds':dist([r['input_commands'] for r in ps]),'totals':{k:sum(r[k] for r in fr) for k in fr[0] if k!='utc_second'} if fr else {}, 'bins_10ms':{k:dist([r[k] for r in bs]) for k in ('out_packets','in_packets','inputs','retry_command_bytes','out_acks','in_acks')}}
 summary['windows'][name]=w
for role in ports:
 d=P/'extracted'/role
 summary['collector'][role]={'resource':json.loads((d/'capture-resource.json').read_text()),'capture_accounting':(d/'capture.log').read_text().splitlines()[-5:], 'retained_files':{f.name:f.stat().st_size for f in d.iterdir() if f.name in ('datagrams.bin','flow-points.csv','input-ports.csv','port-bot.csv','flow-bins.csv','capture.log','flow-summary.json')},'source_hashes':(d/'collector-sha256.txt').read_text()}
 summary['collector'][role]['flow_summary']=json.loads((d/'flow-summary.json').read_text()) if (d/'flow-summary.json').exists() else None
 summary['collector'][role]['malformed_packets']=None
 summary['collector'][role]['first_complete_second']=min(r['utc_second'] for r in flow[role])+1
 summary['collector'][role]['last_complete_second']=max(r['utc_second'] for r in flow[role])
(P/'timing-cadence-analysis.json').write_text(json.dumps(summary,indent=2)+'\n')
(P/'per-bot-intervals.json').write_text(json.dumps(private_bot_intervals)+'\n')
print('Host/socket/Tick and timing/cadence analyses written privately.')
# Align complete wire seconds with bot identity and Running observations bracketing them.
by_sample=[(r['utc_ns'],{v['id']:v for v in r['bots']}) for r in bots]
aligned=[]
for name,(a,b) in windows.items():
 for sec in range(math.ceil(a/1e9),int(b//10**9)):
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
