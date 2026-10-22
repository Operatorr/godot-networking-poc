#!/usr/bin/env python3
"""Read retained Strategy150 evidence only; never launch or mutate a remote workload.

Campaign gates are transcribed from analyze.py; v2 wire counting is retained.
Exact window counters score wire cadence; full UTC seconds supply zero-filled tails.
"""
import csv
import gzip
import hashlib
import json
import math
import pathlib
import re
import statistics
import tarfile
import collections
import analyze
import cpu_report

ROOT=pathlib.Path(__file__).resolve().parents[2]
P=ROOT/'deployment/hetzner/results/udp-capacity150-20261021'
PUBLIC=ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis'
NS=10**9
IDS=set(range(1,151))

def load(path,default=None):
    return json.loads(path.read_text()) if path.exists() else default

def rows(path):
    if not path.exists():return []
    if path.suffix=='.gz':
        with gzip.open(path,'rt') as f:return [json.loads(x) for x in f if x.strip()]
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def csvrows(path):
    if not path.exists():return []
    return [{k:float(v) if k in ('accumulator_lag_s','budget_pct','mean_x','mean_y','mean_radius_sq') else int(v) for k,v in r.items()} for r in csv.DictReader(path.open())]

def dist(values):
    v=[x for x in values if x is not None]
    return {'n':len(v),'min':min(v,default=None),'median':statistics.median(v) if v else None,'p95':analyze.percentile(v,.95),'p99':analyze.percentile(v,.99),'max':max(v,default=None)}

def udp(text):
    lines=text.splitlines()
    for a,b in zip(lines[::2],lines[1::2]):
        if a.startswith('Udp:'):return dict(zip(a.split()[1:],map(int,b.split()[1:])))
    raise ValueError('UDP counters absent')

def sockets(text):
    result=[];lines=text.splitlines()
    for index,line in enumerate(lines[:-1]):
        if 'omega-' not in line:continue
        match=re.search(r'users:\(\("([^"]+)",pid=(\d+),fd=(\d+)\)\).*ino:(\d+)',line)
        memory=re.search(r'skmem:\(([^)]+)\)',lines[index+1])
        if not match or not memory:raise ValueError('Socket attribution unparsed')
        result.append(dict({k:int(v) for k,v in re.findall(r'([a-z]+)(\d+)',memory[1])},pid=int(match[2]),inode=int(match[4]),comm=match[1]))
    return result

def bracket(observations,a,b):
    left=[r for r in observations if r['utc_ns']<=a]
    right=[r for r in observations if r['utc_ns']>=b]
    return (left[-1],right[0]) if left and right else None

def histdiff(a,b):
    return {'count':b['count']-a['count'],'total_ns':b['total_ns']-a['total_ns'],'buckets':[y-x for x,y in zip(a['buckets'],b['buckets'])],'cumulative_max_ns_at_end':b['max_ns']}

def host_window(h,a,b):
    pair=bracket(h,a,b)
    if not pair:return {'complete_bracket':False}
    first,last=pair;selected=[r for r in h if first['utc_ns']<=r['utc_ns']<=last['utc_ns']]
    x,y=udp(first['net/snmp']),udp(last['net/snmp'])
    summary,points=cpu_report.summarize_host(selected,first,last)
    sock=[s for r in selected for s in sockets(r['ss']['stdout'])]
    totals={}
    for s in sock:totals[s['pid'],s['inode']]=max(totals.get((s['pid'],s['inode']),0),s['d'])
    return {'complete_bracket':True,'start_ns':first['utc_ns'],'end_ns':last['utc_ns'],'udp_delta':{k:y[k]-x[k] for k in x},'cpu':summary,'max_socket_receive_bytes':max((s['r'] for s in sock),default=None),'socket_drops_cumulative_max_sum':sum(totals.values()),'rb_values':sorted({s['rb'] for s in sock}),'tb_values':sorted({s['tb'] for s in sock}),'interface_delta':{k:int(last['interface'][k])-int(first['interface'][k]) for k in first['interface']},'maximum_host_sample_gap_s':max(((y['utc_ns']-x['utc_ns'])/NS for x,y in zip(selected,selected[1:])),default=None)}

def main():
    manifest=load(P/'manifest.json',{})
    d=P/'extracted';d.mkdir(exist_ok=True)
    for role in ('game','bots'):
        archive=P/(role+'.tar.gz')
        if archive.exists() and not (d/role).exists():
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    if member.name.startswith('/') or '..' in pathlib.PurePosixPath(member.name).parts or member.issym() or member.islnk():raise ValueError('Unsafe archive member')
                tar.extractall(d,filter='data')
    supplement=P/'game-journal-supplement.tar.gz'
    if supplement.exists() and not (d/'journal-supplement').exists():
        with tarfile.open(supplement) as tar:tar.extractall(d,filter='data')
    ticks=csvrows(d/'game/ticks.csv');server=rows(d/'game/server.ndjson');bots=rows(d/'bots/bots.ndjson')
    host={r:rows(d/r/'host.ndjson.gz') for r in ('game','bots')}
    guard=load(d/'bots/guard-result.json',{})
    start=load(d/'bots/workload-start.json',{}).get('utc_ns');end=guard.get('ended_utc_ns')
    window=manifest.get('window');a,b=(window['start'],window['end']) if window else (None,None)
    out={'namespace':manifest.get('namespace'),'workloads_launched':manifest.get('workloads_launched',0),'requested_population':150,'highest_historical_validated_strategy_population':100,'highest_passing_population_this_observation':None,'classification':'preflight-blocked' if not start else 'pending','window':window,'workload_start_ns':start,'workload_end_ns':end,'controller_decision_ns':manifest.get('controller_decision_utc_ns'),'controller_abort':manifest.get('controller_abort'),'controller_error':manifest.get('controller_error'),'guard_reason':guard.get('reason'),'measurement_duration_s':300,'gates':{},'unknowns':['Application-delivered per-identity inputs','Exact receive-queue residence','Causal instrumentation slowdown','Equal World trajectories: World randomness is entropy-seeded'],'original_binary_sha256':manifest.get('pinned'),'settings':{k:manifest.get(k) for k in ('ramp_limit_s','steady_limit_s','input_hz','seed','stagger_ms','difficulty','game_config','config_proof','candidate_revision','collector_revision','experiment_binary_sha256','collector_source_sha256','capture_duration_change_s','host_limit_s','workload_limit_s','restoration_limit_s')},'cleanup':load(P/'final-verification-summary.json',load(P/'cleanup.json')),'post_journal_cleanup_audit':load(P/'post-journal-audit-summary.json')}
    hashes={}
    for path in (P/'game.tar.gz',P/'bots.tar.gz',P/'udp_capacity150.executed.py',P/'manifest.json',P/'cleanup.json',P/'preserved-measurement-sha256.txt',P/'game-journal-supplement.tar.gz',P/'journal-supplement-verification.json',P/'journal-counts.json',P/'journal-counts-verification.json',P/'post-journal-audit-summary.json',pathlib.Path(__file__)):
        if path.exists():hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    out['hashes']=hashes
    if not start:
        out['gates']['workload_launched']=False
        (PUBLIC/'capacity150-summary.json').write_text(json.dumps(out,indent=2)+'\n');return out
    periods={'full_workload':(start,end),'active_until_decision':(start,min(end,manifest.get('controller_decision_utc_ns',end)))}
    if window:periods['steady_window']=(a,b)
    out['hosts']={};out['collector']={};maps={};portcounts={};coverage={};private={}
    for role in ('game','bots'):
        h=host[role];directory=d/role
        out['hosts'][role]={name:host_window(h,*period) for name,period in periods.items()}
        if h:
            all_sockets=[s for r in h for s in sockets(r['ss']['stdout'])]
            first_error=None
            for x,y in zip(h,h[1:]):
                difference=udp(y['net/snmp'])['RcvbufErrors']-udp(x['net/snmp'])['RcvbufErrors']
                if difference>0:
                    ts=[t for t in ticks if x['utc_ns']<=t['utc_ns']<=y['utc_ns']]
                    first_error={'start_ns':x['utc_ns'],'end_ns':y['utc_ns'],'delta':difference,'elapsed_end_s':(y['utc_ns']-start)/NS,'authenticated':dist([t['authenticated'] for t in ts]),'cpu':cpu_report.interval(x,y),'dropping_sockets':[{k:s[k] for k in ('pid','inode','d','r','rb')} for s in sockets(y['ss']['stdout']) if s['d']>0]};break
            interval=(h[-1]['utc_ns']-h[0]['utc_ns'])/NS
            out['hosts'][role]['first_receive_error']=first_error
            out['hosts'][role]['collector_cpu_percent_one_core']={k:100*(h[-1]['collector_cpu_s'][k]-h[0]['collector_cpu_s'][k])/interval for k in ('self','children')}
            out['hosts'][role]['sample_duration_ms']=dist([r['total_sample_duration_ns']/1e6 for r in h])
            out['hosts'][role]['capture_span']=[h[0]['utc_ns'],h[-1]['utc_ns']]
            alltotals={}
            for s in all_sockets+sockets((directory/'final-sockets.txt').read_text()):alltotals[s['pid'],s['inode']]=max(alltotals.get((s['pid'],s['inode']),0),s['d'])
            out['hosts'][role]['all_observed_socket_drop_sum']=sum(alltotals.values())
            out['hosts'][role]['all_host_udp_delta']={k:udp(h[-1]['net/snmp'])[k]-v for k,v in udp(h[0]['net/snmp']).items()}
            out['hosts'][role]['qdisc_first_last']=[json.loads(h[x]['tc']['stdout']) for x in (0,-1)]
        source_hashes={line.split()[-1].rsplit('/',1)[-1]:line.split()[0] for line in (directory/'collector-sha256.txt').read_text().splitlines()} if (directory/'collector-sha256.txt').exists() else {}
        mapping=csvrows(directory/'port-bot.csv');maps[role]={r['port']:r['bot_id'] for r in mapping}
        unique=len(mapping)==len(maps[role])==len(set(maps[role].values()))
        fs=load(directory/'flow-summary.json',{});ps=load(directory/'parser-status.json',{})
        capture_log=(directory/'capture.log').read_text() if (directory/'capture.log').exists() else ''
        dropped=re.findall(r'(\d+) packets dropped by kernel',capture_log)
        coverage[role]=(fs.get('capture_first_timestamp_ns'),fs.get('capture_last_timestamp_ns'))
        resource=load(directory/'capture-resource.json',{})
        out['collector'][role]={'source_and_executable_sha256':source_hashes,'parser':ps,'flow_summary':fs,'resource':resource,'capture_log_tail':capture_log.splitlines()[-5:],'capture_drops':int(dropped[-1]) if dropped else None,'mapping_count':len(mapping),'mapping_unique':unique,'mapped_identities_complete':set(maps[role].values())==IDS,'capture_span_ns':coverage[role],'retained_bytes':sum((directory/name).stat().st_size for name in ('port-bot.csv','flow-bins.csv','datagrams.bin','flow-points.csv','input-ports.csv','capture.log','flow-summary.json') if (directory/name).exists())}
        portcounts[role]=collections.Counter()
        for r in csvrows(directory/'input-ports.csv'):portcounts[role][r['utc_second'],r['port']]+=r['input_commands']
    for role in host:
        out['hosts'][role]['first_send_buffer_error']=None
        for x,y in zip(host[role],host[role][1:]):
            change=udp(y['net/snmp'])['SndbufErrors']-udp(x['net/snmp'])['SndbufErrors']
            if change:
                out['hosts'][role]['first_send_buffer_error']={'start_ns':x['utc_ns'],'end_ns':y['utc_ns'],'elapsed_end_s':(y['utc_ns']-start)/NS,'delta':change,'cpu':cpu_report.interval(x,y)}
                break
    out['mapping_hosts_agree']=maps['game']==maps['bots']
    out['periods']={}
    for name,(left,right) in periods.items():
        ts=[t for t in ticks if left<=t['utc_ns']<right];sr=[r for r in server if left<=r['utc_ns']<=right and r.get('transport')];br=[r for r in bots if left<=r['utc_ns']<=right]
        result={'requested_start_ns':left,'requested_end_ns':right,'ticks':{}}
        if ts:
            result['ticks']={'count':len(ts),'actual_tick_hz':len(ts)/((right-left)/NS),'work_ms':dist([t['work_ns']/1e6 for t in ts]),'work_over_33_333ms':sum(t['work_ns']>=NS/30 for t in ts),'accumulator_lag_ms':dist([t['accumulator_lag_s']*1000 for t in ts]),'ending_accumulator_lag_ms':ts[-1]['accumulator_lag_s']*1000,'elapsed_tick_lag_end_ms':((ts[-1]['utc_ns']-ts[0]['utc_ns'])/NS-(ts[-1]['tick']-ts[0]['tick'])/30)*1000,'observer_us':dist([t['observer_ns']/1000 for t in ts])}
            for k in ('authenticated','alive','monsters','projectiles','effects','pending_replication','max_deferred_wait_ticks'):
                result['ticks'][k]=dist([t[k] for t in ts])
            first30=[t for t in ts if t['utc_ns']<left+30*NS];last30=[t for t in ts if t['utc_ns']>=right-30*NS]
            result['backlog_first_last_30s']={k:[statistics.mean(t[k] for t in group) if group else None for group in (first30,last30)] for k in ('pending_replication','max_deferred_wait_ticks')}
        if len(sr)>1:
            x,y=sr[0],sr[-1]
            result['transport']={'start_ns':x['utc_ns'],'end_ns':y['utc_ns'],'read_gaps':histdiff(x['transport']['read_gaps'],y['transport']['read_gaps']),'counters':{k:y['transport'][k]-x['transport'][k] for k in x['transport'] if k!='read_gaps'},'phases':{k:histdiff(x['loop_phases'][k],y['loop_phases'][k]) for k in x['loop_phases']},'timing_bounds_us':y['timing_bounds_us']}
        result['delivery_aggregate_s']={k:dist([bot[k] for r in br for bot in r['bots']]) for k in ('snapshot_age_s','confirm_age_s')}
        result['wire']={}
        if all(all(x is not None for x in coverage[role]) for role in maps):
            lo=max(math.ceil(left/NS),*(math.ceil(coverage[r][0]/NS) for r in maps));hi=min(right//NS,*(coverage[r][1]//NS for r in maps))
            selected=[]
            # Only mapped identities with Running samples bracketing a complete second.
            for sec in range(lo,hi):
                pair=bracket(bots,sec*NS,(sec+1)*NS)
                if not pair:continue
                x,y=({v['id']:v for v in row['bots']} for row in pair)
                active={i for i in x.keys()&y.keys() if x[i]['phase']==y[i]['phase']=='Running'}
                inverse={r:{i:p for p,i in maps[r].items()} for r in maps}
                for i in sorted(active):
                    selected.append({'second':sec,'id':i,**{r:portcounts[r].get((sec,inverse[r][i]),0) if i in inverse[r] else None for r in maps}})
            private[name+'-port-seconds']=selected
            result['wire']={'complete_common_utc_seconds':max(0,hi-lo),'complete_second_start':lo,'complete_second_end':hi,'active_bot_seconds':len(selected),'zero_filled_input_counts':{r:dist([v[r] for v in selected]) for r in maps},'zero_input_bot_seconds':{r:sum(v[r]==0 for v in selected) for r in maps},'hosts':{}}
            for role in maps:
                fp=[r for r in csvrows(d/role/'flow-points.csv') if lo<=r['utc_second']<hi]
                bins=[r for r in csvrows(d/role/'flow-bins.csv') if lo*100<=r['utc_10ms']<hi*100]
                result['wire']['hosts'][role]={'totals':{k:sum(r[k] for r in fp) for k in fp[0] if k!='utc_second'} if fp else {},'bins_10ms':{k:dist([r[k] for r in bins]) for k in ('in_packets','out_packets','inputs','retry_command_bytes','in_acks','out_acks')}}
        out['periods'][name]=result
    # Exact cumulative observation endpoints, distinct from raw timestamp coverage.
    botbounds={r['boundary']:r for r in bots if r.get('boundary')}
    serverbounds={r['boundary']:r for r in server if r.get('boundary')}
    out['boundary_lateness_ms']={role:{name:(r['utc_ns']-window[name])/1e6 for name,r in bounds.items() if window and name in window} for role,bounds in (('bots',botbounds),('game',serverbounds))}
    perbot=[]
    if set(botbounds)=={'start','end'}:
        x,y=botbounds['start'],botbounds['end'];old={v['id']:v for v in x['bots']};seconds=(y['mono_ns']-x['mono_ns'])/NS
        deliveryrows=[r for r in bots if a<=r['utc_ns']<b] if window else []
        wire=out['periods'].get('steady_window',{}).get('wire',{})
        for v in y['bots']:
            i=v['id'];u=old[i];observed=[next((v for v in row['bots'] if v['id']==i),None) for row in deliveryrows]
            ages={k:dist([v[k] for v in observed if v]) for k in ('snapshot_age_s','confirm_age_s')}
            samplecomplete=bool(observed) and all(v and v['phase']=='Running' and v['snapshot_age_s'] is not None and v['confirm_age_s'] is not None for v in observed)
            entry={'id':i,'offered_input_hz':(v['inputs']-u['inputs'])/seconds,'boundary_duration_s':seconds,'inputs':[u['inputs'],v['inputs']],'snapshots':[u['snapshots'],v['snapshots']],'confirms':[u['confirms'],v['confirms']],'missed_schedules':v['missed_schedules']-u['missed_schedules'],'input_gaps':[b-a for a,b in zip(u['input_gaps'],v['input_gaps'])],'cumulative_input_gap_max_ms':v['input_gap_max_ms'],'ages_s':ages,'delivery_samples_complete':samplecomplete,'errors_delta':{k:v[k]-u[k] for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')},'wire_input_hz':{},'complete_second_wire_hz_lower_bound':{}}
            for role in maps:
                port=next((p for p,identity in maps[role].items() if identity==i),None)
                count=sum(portcounts[role].get((sec,port),0) for sec in range(wire.get('complete_second_start',0),wire.get('complete_second_end',0))) if port else None
                entry['complete_second_wire_hz_lower_bound'][role]=count/300 if count is not None else None
                fs=out['collector'][role]['flow_summary']
                exact=fs.get('wire_input_counts_by_port',{}).get(str(port))
                entry['wire_input_hz'][role]=exact/300 if exact is not None and fs.get('window')==window else None
            entry['delivery_gate']=samplecomplete and v['snapshots']>u['snapshots'] and v['confirms']>u['confirms'] and ages['snapshot_age_s']['p99']<.250 and ages['confirm_age_s']['p99']<.500 and max(ages['snapshot_age_s']['max'],ages['confirm_age_s']['max'])<1
            perbot.append(entry)
    out['per_bot']=perbot
    out['generator_summary']={'offered_hz':dist([r['offered_input_hz'] for r in perbot]),'wire_hz':{role:dist([r['wire_input_hz'][role] for r in perbot]) for role in maps},'missed_schedules':sum(r['missed_schedules'] for r in perbot) if perbot else None,'delivery_failing_bot_ids':[r['id'] for r in perbot if not r['delivery_gate']],'input_gap_histogram':[sum(r['input_gaps'][i] for r in perbot) for i in range(8)] if perbot else None}
    report=load(d/'bots/bot.json',{})
    out['strict_assertions']=report.get('regression_assertions',report.get('assertions'));out['legacy_harness_criteria']=report.get('success_criteria');out['bot_aggregated']=report.get('aggregated')
    out['full_workload_bot_errors']={k:sum(v[k] for v in bots[-1]['bots']) if bots else None for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics','missed_schedules')}
    out['server_errors']={'full_workload':{k:server[-1][k] for k in ('decode_errors','send_errors')} if server else None,'steady_window':{k:serverbounds['end'][k]-serverbounds['start'][k] for k in ('decode_errors','send_errors')} if set(serverbounds)=={'start','end'} else None}
    journal_directory=d/'journal-supplement' if (d/'journal-supplement').exists() else d/'game'
    journal=rows(journal_directory/('game-journal.ndjson.gz' if journal_directory.name=='journal-supplement' else 'game-journal.ndjson'))
    for row in journal:
        if isinstance(row.get('MESSAGE'),list):row['MESSAGE']=bytes(row['MESSAGE']).decode('utf-8','replace')
    out['journal_summary']=load(journal_directory/'journal-summary.json')
    out['journal_recovery']={'primary_export_failed_on_MESSAGE_byte_array':True,'supplement_verification':load(P/'journal-supplement-verification.json'),'original_primary_bundle_unchanged':True}
    if out['journal_summary']:
        first=out['journal_summary'].pop('first',None)
        if first is not None:out['journal_summary']['first_findings']={key:{'utc_us':value.get('__REALTIME_TIMESTAMP'),'message':value.get('MESSAGE')} for key,value in first.items()}
    out['journal_errors']={name:{'oversized_warnings':sum('oversized' in r.get('MESSAGE','').lower() for r in journal if left<=int(r.get('__REALTIME_TIMESTAMP','0'))*1000<right),'panics':sum('panicked' in r.get('MESSAGE','') for r in journal if left<=int(r.get('__REALTIME_TIMESTAMP','0'))*1000<right)} for name,(left,right) in periods.items()}
    journal_counts=load(P/'journal-counts.json')
    if journal_counts:
        out['journal_counts']={k:v for k,v in journal_counts.items() if k!='seconds'}
        out['journal_counts_verification']=load(P/'journal-counts-verification.json')
        if journal_counts.get('complete_scan'):
            for name,period in journal_counts['periods'].items():
                out['journal_errors'][name]={'oversized_warnings':period['counts'].get('oversized',0),'panics':period['counts'].get('panicked',0),'suppressed_notice_count':period['counts'].get('suppressed',0),'start_ns':period['start_ns'],'end_ns':period['end_ns'],'payload_bytes_min_max':period['oversized_payload_bytes_min_max']}
    if periods['active_until_decision']==periods['full_workload'] and journal_counts and journal_counts.get('complete_scan'):
        out['journal_errors']['active_until_decision']=dict(out['journal_errors']['full_workload'])
    elif not (out['journal_summary'] or {}).get('complete'):
        out['journal_errors']['active_until_decision']={'oversized_warnings':None,'panics':None,'reason':'bounded journal prefix; no exact counter interval'}
    # Preserve only non-sensitive assertion output; addresses are checked before publishing.
    g=out['gates'];g['complete_300s_common_coverage']=bool(window and b-a==300*NS and ticks and ticks[0]['utc_ns']<=a and ticks[-1]['utc_ns']>=b and all(c[0] is not None and c[0]<=a and c[1]>=b for c in coverage.values()) and all(bracket(h,a,b) for h in host.values()) and set(botbounds)==set(serverbounds)=={'start','end'} and botbounds['start']['utc_ns']<a+NS and botbounds['end']['utc_ns']>=b)
    g['collectors_clean']=all(v['parser'].get('status')=='eof' and v['parser'].get('parse_errors')==0 and v['capture_drops']==0 and v['resource'].get('exit_code')==0 and v['resource'].get('reason')=='controller-stop' and v['flow_summary'].get('window')==window and v['flow_summary'].get('schedule_observed_utc_ns',b or 0)<(a or 0) for v in out['collector'].values())
    g['identity_mapping']=out['mapping_hosts_agree'] and all(v['mapping_unique'] and v['mapped_identities_complete'] for v in out['collector'].values())
    polls=rows(P/'status-polls.ndjson');fresh=manifest.get('pre_swarm_runtime',{})
    g['runtime_identity']=bool(polls) and all(r['observations']['game']['identity']==fresh.get('identity') and r['observations']['game']['exe_sha256']==manifest['experiment_binary_sha256']['game'] for r in polls)
    out['polling']={'count':len(polls),'query_duration_ms':dist([(r['end_ns']-r['start_ns'])/1e6 for r in polls]),'start_cadence_s':dist([(y['start_ns']-x['start_ns'])/NS for x,y in zip(polls,polls[1:])]),'separate_map_ssh_reads':0}
    g['per_identity_offered_29_7hz']=len(perbot)==150 and all(r['offered_input_hz']>=29.7 for r in perbot)
    g['mapped_wire_29_7hz']=len(perbot)==150 and all(all(v is not None and v>=29.7 for v in r['wire_input_hz'].values()) for r in perbot)
    g['delivery']=len(perbot)==150 and all(r['delivery_gate'] for r in perbot)
    measured=out['periods'].get('steady_window',{});t=measured.get('ticks',{})
    auth=[r for r in server if window and a<=r['utc_ns']<=b]
    g['all_150_authenticated']=bool(t) and t['authenticated']['min']==t['authenticated']['max']==150 and bool(auth) and all(len(r['players'])==150 for r in auth) and len({tuple(sorted(v[0] for v in r['players'])) for r in auth})==1
    for role in ('game','bots'):
        values=out['hosts'][role].get('steady_window',{}).get('udp_delta',{})
        g[role+'_udp_errors_zero']=bool(values) and all(values.get(k)==0 for k in ('RcvbufErrors','SndbufErrors','InErrors','MemErrors','InCsumErrors'))
    g['tick_hz']=bool(t) and t['actual_tick_hz']>=29.7
    g['tick_work_p99']=bool(t) and t['work_ms']['p99']<33.333
    g['ending_lag']=bool(t) and t['elapsed_tick_lag_end_ms']<100 and t['ending_accumulator_lag_ms']<100
    wait=measured.get('backlog_first_last_30s',{}).get('max_deferred_wait_ticks',[None,None])
    growing=None if None in wait else wait[1]>wait[0]+30 and t['max_deferred_wait_ticks']['max']>60
    out['growing_replication_backlog_campaign_rule']=growing;g['replication_backlog']=growing is False
    agg=report.get('aggregated',{})
    g['application_errors_zero']=bool(agg) and all(agg.get(k)==0 for k in ('total_decode_failures','total_send_failures','total_panics','disconnected_bots')) and out['server_errors']['steady_window']=={'decode_errors':0,'send_errors':0} and out['journal_errors'].get('steady_window',{}).get('panics')==0
    assertions=out['strict_assertions']
    # Actual assertion report schema is validated below; unknown schemas fail closed.
    g['strict_enabled_assertions']=False
    assertion_rows=assertions if isinstance(assertions,list) else assertions.get('results',[]) if isinstance(assertions,dict) else []
    if assertion_rows:
        enabled=[r for r in assertion_rows if not r.get('skipped',False)]
        g['strict_enabled_assertions']={r.get('name') for r in enabled}>={'aoi_cull','decode_clean'} and all(r.get('passed') is True for r in enabled)
    g['journal_error_counts_complete']=bool(journal_counts and journal_counts.get('complete_scan') and out['journal_counts_verification'].get('equal') and journal_counts['records_scanned']==out['journal_summary']['records'])
    out['collector_valid']=all(g[k] for k in ('complete_300s_common_coverage','collectors_clean','identity_mapping','runtime_identity','journal_error_counts_complete'))
    out['generator_valid']=out['collector_valid'] and all(g[k] for k in ('per_identity_offered_29_7hz','mapped_wire_29_7hz','bots_udp_errors_zero'))
    out['classification']='collector-invalid' if not out['collector_valid'] else 'generator-invalid' if not out['generator_valid'] else 'capacity-pass-with-correctness-findings' if all(g.values()) else 'valid-failure'
    if all(g.values()):out['highest_passing_population_this_observation']=150
    out['failed_gates']=[k for k,v in g.items() if not v]
    out['runtime_proof']={'pre_swarm_identity':fresh.get('identity'),'pre_swarm_executable_sha256':fresh.get('exe_sha256'),'same_identity_polls':sum(r['observations']['game']['identity']==fresh.get('identity') for r in polls),'window_publication_lead_s':(a-manifest['window_published_ns'])/NS if window else None,'bots_exit_verified_ns':manifest.get('bots_exit_verified_utc_ns'),'game_stopped_ns':manifest.get('game_stopped_utc_ns')}
    out['bot_observer_cost']={'completed_samples':bots[-1].get('completed_samples'),'completed_observer_ns':bots[-1].get('completed_observer_ns')} if bots else None
    private['raw_bot_report']=report
    private['per_bot_detailed']=perbot
    out['per_bot']=[{k:r[k] for k in ('id','offered_input_hz','wire_input_hz','inputs','snapshots','confirms','missed_schedules','cumulative_input_gap_max_ms','errors_delta','delivery_samples_complete','delivery_gate')} | {'snapshot_age_p99_ms':r['ages_s']['snapshot_age_s']['p99']*1000 if r['ages_s']['snapshot_age_s']['p99'] is not None else None,'snapshot_age_max_ms':r['ages_s']['snapshot_age_s']['max']*1000 if r['ages_s']['snapshot_age_s']['max'] is not None else None,'confirm_age_p99_ms':r['ages_s']['confirm_age_s']['p99']*1000 if r['ages_s']['confirm_age_s']['p99'] is not None else None,'confirm_age_max_ms':r['ages_s']['confirm_age_s']['max']*1000 if r['ages_s']['confirm_age_s']['max'] is not None else None} for r in perbot]
    (P/'capacity150-private-analysis.json').write_text(json.dumps(private)+'\n')
    # Host addresses and credentials stay private, including nested logs.
    access=load(ROOT/'deployment/hetzner/access.local.json')
    text=json.dumps(out,indent=2)+'\n'
    for h in access['servers']:
        text=text.replace(h['ipv4'],'[private-endpoint]')
    (PUBLIC/'capacity150-summary.json').write_text(text)
    print(json.dumps({k:out[k] for k in ('classification','workloads_launched','failed_gates','highest_passing_population_this_observation')}))
    return out

if __name__=='__main__':main()
