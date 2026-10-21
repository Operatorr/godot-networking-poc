#!/usr/bin/env python3
"""Offline generator diagnostic analysis. Full rows remain private; no workload launch."""
import collections
import csv
import gzip
import hashlib
import json
import math
import pathlib
import re
import statistics
import tarfile
from collections import Counter
import udp_capacity150_analysis as base
ROOT=pathlib.Path(__file__).resolve().parents[2]
P=ROOT/'deployment/hetzner/results/udp-generator-profile-20261021'
PUBLIC=ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis'
NS=10**9
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
    decoded=base.load(directory/'decode-summary.json')
    if decoded:
        if decoded['raw_rc']!=0 or decoded['script_rc']!=0:raise ValueError('Offline decoding incomplete')
        loss=Counter(decoded['record_counts'])
    if loss['PERF_RECORD_SAMPLE'] != len(samples):raise ValueError('Raw/decoded sample count mismatch')
    measured = [r for r in anchors if r.get('target_stat')]
    def cpu(row):
        fields = row['target_stat'].rsplit(')', 1)[1].split()
        return int(fields[11]) + int(fields[12])
    cpu_seconds = (cpu(measured[-1]) - cpu(measured[0])) / status['clock_ticks_per_second']
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


def interval_evidence(directory, a, b):
    bots=base.rows(directory/'bots/bots.ndjson');ticks=base.csvrows(directory/'game/ticks.csv')
    server=base.rows(directory/'game/server.ndjson')
    requested=(a,b)
    if not bots or not ticks or b<=bots[0]['utc_ns'] or a>=bots[-1]['utc_ns']:
        return {'requested_start_ns':a,'requested_end_ns':b,'available':False,'reason':'outside retained workload coverage','offered_hz':None,'wire_hz':None,'tick_hz':None}
    a=max(a,bots[0]['utc_ns'],ticks[0]['utc_ns']);b=min(b,bots[-1]['utc_ns'],ticks[-1]['utc_ns'])
    inside=[r for r in bots if a<=r['utc_ns']<=b]
    ts=[r for r in ticks if a<=r['utc_ns']<b]
    offered=[];missed=0;gaps=[0]*8;errors=Counter()
    if len(inside)>=2:
        x,y=inside[0],inside[-1];duration=(y['mono_ns']-x['mono_ns'])/NS
        first={r['id']:r for r in x['bots']}
        for row in y['bots']:
            old=first.get(row['id'])
            if not old:continue
            offered.append((row['inputs']-old['inputs'])/duration)
            missed+=row['missed_schedules']-old['missed_schedules']
            gaps=[n+j-i for n,i,j in zip(gaps,old['input_gaps'],row['input_gaps'])]
            errors.update({k:row[k]-old[k] for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')})
    result={'requested_start_ns':requested[0],'requested_end_ns':requested[1],'available':True,'complete_requested_interval':(a,b)==requested,'start_ns':a,'end_ns':b,'bot_observation_bracket_ns':[inside[0]['utc_ns'],inside[-1]['utc_ns']] if inside else None,
            'offered_hz':base.dist(offered),'missed_schedules':missed if offered else None,'input_gap_histogram':gaps if offered else None,
            'bot_errors':dict(errors),'snapshot_age_ms':base.dist([v['snapshot_age_s']*1000 for r in inside for v in r['bots'] if v['snapshot_age_s'] is not None]),
            'confirm_age_ms':base.dist([v['confirm_age_s']*1000 for r in inside for v in r['bots'] if v['confirm_age_s'] is not None]),
            'authenticated':base.dist([r['authenticated'] for r in ts]),'living':base.dist([r['alive'] for r in ts]),
            'tick_count':len(ts),'tick_hz':len(ts)/((b-a)/NS),'tick_work_ms':base.dist([r['work_ns']/1e6 for r in ts]),'hosts':{}}
    sr=[r for r in server if a<=r['utc_ns']<=b]
    if len(sr)>1:
        x,y=sr[0],sr[-1]
        result['game_transport']={'bracket_ns':[x['utc_ns'],y['utc_ns']],'counters':{k:y['transport'][k]-x['transport'][k] for k in x['transport'] if k!='read_gaps'},'read_gaps':base.histdiff(x['transport']['read_gaps'],y['transport']['read_gaps'])}
    lo=math.ceil(a/NS);hi=b//NS
    for role in ('game','bots'):
        d=directory/role;host=base.host_window(base.rows(d/'host.ndjson.gz'),a,b)
        mapping=base.csvrows(d/'port-bot.csv');counts=Counter()
        for row in base.csvrows(d/'input-ports.csv'):
            if lo<=row['utc_second']<hi:counts[row['port']]+=row['input_commands']
        fp=[r for r in base.csvrows(d/'flow-points.csv') if lo<=r['utc_second']<hi]
        host.pop('cpu',None)
        h=base.rows(d/'host.ndjson.gz');pair=base.bracket(h,a,b)
        host['cpu']=base.cpu_report.interval(*pair) if pair else None
        inner=[r for r in h if a<=r['utc_ns']<=b]
        host['cpu_inner_observation']=base.cpu_report.interval(inner[0],inner[-1]) if len(inner)>=2 else None
        host['whole_wire_seconds']=[lo,hi]
        host['wire_hz']=base.dist([counts[r['port']]/(hi-lo) for r in mapping]) if hi>lo else None
        host['wire_totals']={k:sum(r[k] for r in fp) for k in fp[0] if k!='utc_second'} if fp else {}
        result['hosts'][role]=host
    return result


def main():
    d=P/'extracted';d.mkdir(exist_ok=True)
    for role in ('game','bots'):
        if not (d/role).exists():
            with tarfile.open(P/(role+'.tar.gz')) as archive:archive.extractall(d,filter='data')
    journal=base.load(d/'game/journal-summary.json')
    if journal:
        # Adapter for unchanged historical analysis: complete compact scan, never prefix-as-full.
        normalized=dict(journal,records_scanned=journal['records'])
        for period in normalized['periods'].values():period['oversized_payload_bytes_min_max']=None
        (P/'journal-counts.json').write_text(json.dumps(normalized))
        (P/'journal-counts-verification.json').write_text(json.dumps({'equal':True,'provenance':'journal inside independently SHA-256 verified game.tar.gz'}))
    base.P=P;base.PUBLIC=P
    full=base.main()
    full['journal_recovery']={'primary_export_byte_aware':True,'complete_scan':bool(journal and journal['complete_scan']),'raw_retention_complete':bool(journal and journal['complete'])}
    full['highest_passing_population_this_observation']=None
    full['classification']='aborted-controller-profile-exit-classification' if full.get('controller_abort')=='profile-failure:early-recording-failed' else 'diagnostic-profiled-'+full['classification']
    (P/'full-analysis.json').write_text(json.dumps(full)+'\n')
    phase=base.load(d/'bots/phase.json')['phase2_utc_ns']
    profiles={}
    for name in ('early','late'):
        directory=d/'bots'/name
        status=base.load(directory/'profile-status.json',{})
        result={'status':status}
        if not status:
            profiles[name]={'status':{},'available':False,'reason':'not recorded after controller abort','sample_count':None,'effective_samples_per_target_cpu_s':None,'hotpaths':None}
            continue
        try:
            samples,info=parse_profile(directory)
            hot=summarize_samples(samples,0,2**63)
            result.update(info);result['hotpaths']=hot
            result['actual_first_last_offsets_s']=[(info[k]-phase)/NS for k in ('first_sample_utc_ns','last_sample_utc_ns')]
            enabled=status.get('enabled_anchor');disabled=status.get('disabled_anchor')
            result['enabled_disabled_offsets_s']=[(v['utc_ns']-phase)/NS for v in (enabled,disabled)] if enabled and disabled else None
            result['observed_active_s']=(disabled['monotonic_ns']-enabled['monotonic_ns'])/NS if enabled and disabled else None
            result['missed_early_prefix_s']=(enabled['utc_ns']-status['nominal_start_ns'])/NS if enabled else None
            result['perf_data_sha256']=hashlib.sha256((directory/'perf.data').read_bytes()).hexdigest()
            (P/(name+'-sample-addresses.json')).write_text(json.dumps(samples))
        except Exception as error:result['analysis_error']=str(error)
        profiles[name]=result
    (P/'profile-analysis.json').write_text(json.dumps(profiles,indent=2)+'\n')
    windows={name:interval_evidence(d,phase+x*NS,phase+y*NS) for name,x,y in (
        ('early_profile_nominal',0,25),('early_adjacent_off',25,50),
        ('late_adjacent_before',155,180),('late_profile_nominal',180,205),('late_adjacent_after',205,230))}
    (P/'window-analysis.json').write_text(json.dumps(windows,indent=2)+'\n')
    public={k:full[k] for k in ('namespace','workloads_launched','classification','window','workload_start_ns','workload_end_ns','controller_abort','controller_error','guard_reason','gates','failed_gates','generator_summary','full_workload_bot_errors','server_errors','strict_assertions','settings','runtime_proof','polling','bot_observer_cost','cleanup')}
    public.update(new_validated_capacity=None,highest_historical_validated_strategy_population=100,
                  unknowns={k:None for k in ('application_delivered_inputs','projectile_owner_map_occupancy','poll_cycle_duration','receive_queue_residence','causal_profiler_slowdown')},
                  phase2_utc_ns=phase,profiles={},comparison_windows=windows,journal={k:v for k,v in journal.items() if k not in ('seconds','first_findings')} if journal else None,
                  measurement={k:full['periods'].get('steady_window',{}).get(k) for k in ('ticks','backlog_first_last_30s','delivery_aggregate_s')},hosts={},collectors={},evidence_sha256={})
    for name,p in profiles.items():
        public['profiles'][name]={k:v for k,v in p.items() if k!='status'}
        status=p['status']
        public['profiles'][name]['recording']={k:status.get(k) for k in ('target_identity','phase2_utc_ns','offset_s','nominal_start_ns','nominal_end_ns','reason','rc','elapsed_s','profiler_cpu_s','profiler_maxrss_kib','supervisor_cpu_s','supervisor_maxrss_kib','file_bytes','clock_ticks_per_second','error')}
        public['profiles'][name]['cpu_clock_anchors']={key:{k:v for k,v in status.get(key,{}).items() if k in ('utc_ns','monotonic_ns')} for key in ('initial_anchor','enabled_anchor','disable_requested_anchor','disabled_anchor','ended_anchor')}
        for key,point in public['profiles'][name]['cpu_clock_anchors'].items():
            for process in ('target','profiler','supervisor'):
                raw=status.get(key,{}).get(process+'_stat')
                fields=raw.rsplit(')',1)[1].split() if raw else None
                point[process+'_cpu_ticks']=int(fields[11])+int(fields[12]) if fields else None
                point[process+'_rss_pages']=int(fields[21]) if fields else None
        hot=public['profiles'][name].get('hotpaths')
        if hot:
            hot.pop('top_stacks',None)
            for key in ('top_self','top_inclusive'):hot[key]=hot[key][:12]
    public['capacity_gates_scored']=False
    public['gate_interpretation']='Historical analyzer fails closed for missing measurement data; no 300-second measurement occurred. False gates here are not observed capacity failures.'
    if public.get('journal'):
        for period in public['journal']['periods'].values():
            period['interval_observed']=period['end_ns']<=full.get('runtime_proof',{}).get('game_stopped_ns',0)
            if not period['interval_observed']:period['counts']=None
    public['profile_supervisor']={k:v for k,v in base.load(d/'bots/profile-supervisor-status.json',{}).items() if k!='profiles'}
    for role in ('game','bots'):
        h=full['hosts'][role]
        public['hosts'][role]={k:v for k,v in h.items() if k not in ('qdisc_first_last','full_workload','active_until_decision','steady_window')}
        public['hosts'][role]['steady_window']={k:v for k,v in h.get('steady_window',{}).items() if k!='cpu'}
        public['hosts'][role]['steady_cpu']=h.get('steady_window',{}).get('cpu',{}).get('matched_boundary')
        c=full['collector'][role]
        public['collectors'][role]={k:c[k] for k in ('parser','resource','capture_drops','mapping_count','mapping_unique','mapped_identities_complete','capture_span_ns','retained_bytes')}
        public['collectors'][role]['flow_counters']={k:v for k,v in c['flow_summary'].items() if k not in ('wire_input_counts_by_port','ports','per_port') and not isinstance(v,list)}
    public['early_disassembly_attribution']=base.load(P/'early-disassembly-attribution.json')
    public['decode_provenance']=base.load(P/'extracted/bots/early/decode-summary.json')
    public['offline_archive_verification']=base.load(P/'offline-verification.json')
    for path in list(P.glob('*.tar.gz'))+[P/'manifest.json',P/'cleanup.json',P/'final-verification-summary.json',P/'udp_generator_profile.executed.py',P/'udp_generator_profile_record.py.executed',P/'udp_generator_profile_journal.py.executed',P/'preserved-measurement-sha256.txt',pathlib.Path(__file__)]:
        if path.exists():public['evidence_sha256'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    # One top-level entry per line is compact while retaining all exact aggregates.
    text='{\n'+',\n'.join('  '+json.dumps(k)+': '+json.dumps(v,sort_keys=True) for k,v in public.items())+'\n}\n'
    access=base.load(ROOT/'deployment/hetzner/access.local.json')
    for host in access['servers']:text=text.replace(host['ipv4'],'[private-endpoint]')
    (PUBLIC/'generator-profile-summary.json').write_text(text)
    print(json.dumps({k:public[k] for k in ('classification','workloads_launched','failed_gates')}))
    return public

if __name__=='__main__':main()
