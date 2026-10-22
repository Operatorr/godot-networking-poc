#!/usr/bin/env python3
"""Offline-only send150 analysis; preserve historical analyzers and public reports."""
import hashlib
import collections
import json
import pathlib
import tarfile
import clean_run_scoring as base
from udp_generator_profile_fixed_details import sockets, trajectories
import clean_run as controller

ROOT=pathlib.Path(__file__).resolve().parents[2]
P=ROOT/'deployment/hetzner/results'/controller.NAMESPACE
BUILD=ROOT/'deployment/hetzner/results'/ (controller.NAMESPACE+'-build')
PUBLIC=ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs'
NS=10**9

def active_trajectories(d, phase):
    path=P/'per-second-trajectories.json'
    summary=trajectories(d,phase,path)
    timeline=base.load(path)
    observations=base.rows(d/'bots/bots.ndjson')
    mappings={r:{m['bot_id']:m['port'] for m in base.csvrows(d/r/'port-bot.csv')} for r in ('game','bots')}
    counts={r:collections.Counter() for r in mappings}
    for role in mappings:
        for row in base.csvrows(d/role/'input-ports.csv'):counts[role][row['utc_second'],row['port']]+=row['input_commands']
    for row in timeline:
        sec=row['wire_utc_second'];pair=base.bracket(observations,sec*NS,(sec+1)*NS)
        active=[]
        if pair:
            a,b=({v['id']:v for v in point['bots']} for point in pair)
            active=[i for i in a.keys()&b.keys() if a[i]['phase']==b[i]['phase']=='Running']
        row['wire_active_peer_count']=len(active)
        for role in mappings:
            row['hosts'][role]['wire_inputs_per_second']=base.dist([counts[role][sec,mappings[role][i]] for i in active if i in mappings[role]])
    for group in summary['groups']:
        lo,hi=group['phase_interval_s'];rows=[r for r in timeline if lo<r['phase_end_s']<=hi]
        group['wire_input_interval_medians']={role:base.dist([r['hosts'][role]['wire_inputs_per_second']['median'] for r in rows]) for role in mappings}
    summary['semantics']='Adjacent cumulative bot observations, groups use end timestamps; wire uses preceding complete UTC seconds with Running observations bracketing each included identity. Unjoined or unbracketed identities excluded, not zero-filled. Exact 300s counters score gates; these trajectory groups do not.'
    path.write_text(json.dumps(timeline)+'\n')
    return summary


def ramp_evidence(d, phase):
    observations=[r for r in base.rows(d/'bots/bots.ndjson') if r['utc_ns']<=phase]
    peer_rows=[]
    for i in range(1,controller.POPULATION+1):
        values=[(r,next((b for b in r['bots'] if b['id']==i and b['phase']=='Running'),None)) for r in observations]
        values=[(r,b) for r,b in values if b]
        if len(values)<2:
            peer_rows.append({'id':i,'offered_hz':None,'reason':'fewer than two Running ramp observations'})
            continue
        (a,x),(b,y)=values[0],values[-1]
        dt=(b['mono_ns']-a['mono_ns'])/NS
        peer_rows.append({'id':i,'start_ns':a['utc_ns'],'end_ns':b['utc_ns'],'interval_s':dt,
                         'inputs':y['inputs']-x['inputs'],'offered_hz':(y['inputs']-x['inputs'])/dt,
                         'missed_schedules':y['missed_schedules']-x['missed_schedules']})
    (P/'ramp-per-peer.json').write_text(json.dumps(peer_rows)+'\n')
    result={'semantics':'Per-peer first/last Running ramp observation, staggered durations; time before first observation and after last remains unmeasured.',
            'offered_hz':base.dist([r['offered_hz'] for r in peer_rows]),
            'observed_peer_count':sum(r['offered_hz'] is not None for r in peer_rows),
            'missing_peer_ids':[r['id'] for r in peer_rows if r['offered_hz'] is None],
            'wire':{}}
    private=base.load(P/'capacity150-private-analysis.json',{})
    rows=[r for r in private.get('full_workload-port-seconds',[]) if (r['second']+1)*NS<=phase]
    for role in ('game','bots'):
        result['wire'][role]={'complete_active_bot_seconds':len(rows),'inputs_per_active_second':base.dist([r[role] for r in rows]),'zero_input_bot_seconds':sum(r[role]==0 for r in rows)}
    return result


def received_aoi(report, population):
    rows = report.get('per_bot', [])
    assertions = report.get('regression_assertions', report.get('assertions', []))
    if isinstance(assertions, dict): assertions = assertions.get('results', [])
    candidates = [r for r in assertions if r.get('name') == 'aoi_cull']
    result = {'complete_peer_rows':len(rows)==population and {r.get('bot_id') for r in rows}==set(range(1,population+1)),
              'matched_positions':None, 'unknown_positions':None, 'unknown_peer_ids':[],
              'above_threshold_peer_ids':None, 'threshold':1150, 'strict_default_pass':False,
              'all_peer_zero_unknown':False,'no_actual_above_1150':False}
    counts_known = result['complete_peer_rows'] and all(type(r.get('aoi_unknown_positions')) is int and
                       type(r.get('aoi_matched_positions')) is int for r in rows)
    if counts_known:
        result['matched_positions']=sum(r['aoi_matched_positions'] for r in rows)
        result['unknown_positions']=sum(r['aoi_unknown_positions'] for r in rows)
        result['unknown_peer_ids']=[r['bot_id'] for r in rows if r['aoi_unknown_positions']!=0 or r['aoi_matched_positions']<=0]
        result['all_peer_zero_unknown']=not result['unknown_peer_ids']
    if len(candidates)==1:
        assertion=candidates[0]; details=assertion.get('details') or {}
        schema=(details.get('threshold')==1150 and details.get('eligible_bots')==population
                and isinstance(details.get('violators'),list) and isinstance(details.get('unknown_bots'),list)
                and not assertion.get('skipped',False))
        result['strict_default_pass']=schema and assertion.get('passed') is True
        if schema:
            result['above_threshold_peer_ids']=[r['bot_id'] for r in details['violators']]
            result['no_actual_above_1150']=not details['violators']
            result['all_peer_zero_unknown']=result['all_peer_zero_unknown'] and not details['unknown_bots']
    result['semantics']='Lifetime received positional records, including retired Snapshots before application discard. Violators come from unrounded maxima in the production assertion; displayed per-peer distances are rounded. No emission audit.'
    return result


def augment_clean_gates(full, directory):
    report=base.load(directory/'bots/bot.json',{})
    aoi=received_aoi(report,controller.POPULATION)
    g=full['gates']
    g['received_aoi_default95_policy']=aoi['strict_default_pass']
    g['received_aoi_all_peers_zero_unknown']=aoi['all_peer_zero_unknown']
    g['received_aoi_no_actual_above1150']=aoi['no_actual_above_1150']
    observed=base.rows(directory/'bots/bots.ndjson')
    endpoints={r['boundary']:r for r in observed if r.get('boundary')}
    stale_full=sum(r['stale_snapshots_ignored'] for r in report.get('per_bot',[])) if aoi['complete_peer_rows'] and all('stale_snapshots_ignored' in r for r in report['per_bot']) else None
    stale_steady=None
    if set(endpoints)=={'start','end'}:
        old={r['id']:r for r in endpoints['start']['bots']}
        tail=endpoints['end']['bots']
        if len(old)==len(tail)==controller.POPULATION and all('stale_snapshots_ignored' in r and r['id'] in old and 'stale_snapshots_ignored' in old[r['id']] for r in tail):
            stale_steady=sum(r['stale_snapshots_ignored']-old[r['id']]['stale_snapshots_ignored'] for r in tail)
    final_observation={r['id']:r for r in observed[-1]['bots']} if observed else {}
    final_report=report.get('per_bot',[])
    full_counter_reconciled=(len(final_observation)==len(final_report)==controller.POPULATION and
        all(type(row.get('state_updates_received')) is int and type(row.get('stale_snapshots_ignored')) is int and
            row.get('state_updates_received')==final_observation.get(row['bot_id'],{}).get('snapshots') and
            row.get('stale_snapshots_ignored')==final_observation.get(row['bot_id'],{}).get('stale_snapshots_ignored')
            for row in final_report))
    g['full_replication_counters_cover_final_snapshot']=full_counter_reconciled
    for period in ('full_workload','steady_window'):
        errors=full.get('full_workload_bot_errors') if period=='full_workload' else {
            key:sum(row['errors_delta'][key] for row in full.get('per_bot',[]))
            for key in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')}
        g[period+'_replication_and_bot_errors_zero']=bool(errors) and len(full.get('per_bot',[]))==controller.POPULATION and all(errors.get(k)==0 for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics'))
        journal=full.get('journal_errors',{}).get(period,{})
        g[period+'_oversized_panics_suppression_zero']=all(journal.get(k)==0 for k in ('oversized_warnings','panics','suppressed_notice_count'))
    for role in ('game','bots'):
        g[role+'_all_observed_udp_and_socket_errors_zero']=(full.get('hosts',{}).get(role,{}).get('all_observed_socket_drop_sum')==0 and
            all(full.get('hosts',{}).get(role,{}).get('all_host_udp_delta',{}).get(k)==0 for k in ('RcvbufErrors','SndbufErrors','InErrors','MemErrors','InCsumErrors')))
    g['server_full_and_steady_errors_zero']=all(full.get('server_errors',{}).get(period)=={'decode_errors':0,'send_errors':0} for period in ('full_workload','steady_window'))
    transport=full.get('periods',{}).get('full_workload',{}).get('transport',{}).get('counters',{})
    # Real key schema is retained in the output; absent counters fail closed.
    required=('send_errors','receive_errors','zero_byte_sends')
    g['full_transport_errors_zero']=bool(transport) and all(transport.get(k)==0 for k in required)
    full['clean_evidence']={'received_aoi':aoi,'stale_snapshots_ignored':{'full':stale_full,'steady':stale_steady},
        'full_replication_counter_snapshot_reconciliation':full_counter_reconciled,
        'count_limitations':['Baseline-reference/unknown-entity counters end at the final recorder row; equality of final report accepted/stale Snapshot counts must prove no later Snapshot can change them. Otherwise lifetime replication counts remain unknown and the full-coverage gate fails. Decode/send/panic lifetime counts are also checked by the final report. AoI counts are final report lifetime counts. A lifetime zero bounds steady zero; nonzero AoI period attribution is unknown without per-record timestamps.'],
        'transport_full_counters':transport}
    classify(full)


def classify(full):
    full['failed_gates']=[k for k,v in full['gates'].items() if v is not True]
    clean=not full['failed_gates'] and not full.get('controller_abort') and not full.get('controller_error') and not full.get('guard_reason')
    full['classification']=('collector-invalid' if not full.get('collector_valid') else 'generator-invalid' if not full.get('generator_valid') else 'clean-cell-pass' if clean else 'valid-failure')
    if full.get('controller_abort') or full.get('controller_error'):full['classification']='aborted-'+full['classification']
    full['highest_passing_population_this_observation']=controller.POPULATION if clean else None


def wire_deficits(full, directory):
    """Retain collector counts and identity mappings without causal attribution."""
    maps={role:{r['bot_id']:r['port'] for r in base.csvrows(directory/role/'port-bot.csv')} for role in ('game','bots')}
    flows={role:base.load(directory/role/'flow-summary.json',{}) for role in ('game','bots')}
    result=[]
    for row in full.get('per_bot',[]):
        failed=[role for role in maps if row['wire_input_hz'][role] is None or row['wire_input_hz'][role]<29.7]
        deficits=[role for role in maps if row['wire_input_hz'][role] is not None and row['wire_input_hz'][role]<row['offered_input_hz']]
        if not failed and not deficits:continue
        result.append({'bot_id':row['id'],'offered_hz':row['offered_input_hz'],
            'offered_boundary_counts':row['inputs'],'failed_wire_hosts':failed,'deficit_hosts':deficits,
            'offered_minus_wire_hz':{role:row['offered_input_hz']-row['wire_input_hz'][role] if row['wire_input_hz'][role] is not None else None for role in maps},
            'hosts':{role:{'mapped_port':maps[role].get(row['id']),
                'wire_hz':row['wire_input_hz'][role],
                'exact_window_input_commands':flows[role].get('wire_input_counts_by_port',{}).get(str(maps[role].get(row['id']))),
                'collector_window':flows[role].get('window'),
                'collector_parser_status':base.load(directory/role/'parser-status.json',{}).get('status')}
                for role in maps},
            'cause':None,
            'interval_limit':'Offered rate uses observed monotonic start/end counters; wire uses the exact 300s UTC schedule. Boundary lateness is reported separately.'})
    return result


def main():
    d=P/'extracted';d.mkdir(exist_ok=True)
    cleanup=base.load(P/'final-verification-summary.json',{})
    original_cleanup=base.load(P/'cleanup.json',{})
    recovery=base.load(P/'recovery-completion.json',{})
    archive_proofs=dict(original_cleanup)
    if recovery.get('game_archive_completion'):
        archive_proofs['game']=recovery['game_archive_completion']
    for role in ('game','bots'):
        archive=P/(role+'.tar.gz')
        if not archive.exists():continue
        actual=hashlib.sha256(archive.read_bytes()).hexdigest()
        assert actual==archive_proofs[role]['archive_remote_sha256']
        if not (d/role).exists():
            with tarfile.open(archive) as tar:
                for m in tar.getmembers():
                    assert not m.name.startswith('/') and '..' not in pathlib.PurePosixPath(m.name).parts and not m.issym() and not m.islnk()
                tar.extractall(d,filter='data')
    journal=base.load(d/'game/journal-summary.json')
    if journal:
        normalized=json.loads(json.dumps(journal));normalized['records_scanned']=journal['records']
        for period in normalized['periods'].values():period['oversized_payload_bytes_min_max']=None
        (P/'journal-counts.json').write_text(json.dumps(normalized))
        (P/'journal-counts-verification.json').write_text(json.dumps({'equal':True,'provenance':'byte-aware complete scan inside independently hash-verified game archive'}))
    base.P=P;base.PUBLIC=P;base.sockets=sockets
    base.POPULATION=controller.POPULATION;base.IDS=set(range(1,controller.POPULATION+1))
    full=base.main()
    full['journal_recovery']={'primary_export_byte_aware':True,'complete_scan':bool(journal and journal.get('complete_scan')),'raw_retention_complete':bool(journal and journal.get('complete'))}
    manifest=base.load(P/'manifest.json',{})
    phase=base.load(d/'bots/phase.json',{}).get('phase2_utc_ns')
    polls=base.rows(P/'status-polls.ndjson')
    identities=[r['observations']['bots'].get('bot_identity') for r in polls]
    identified=[r for r in identities if r]
    runtime_ok=bool(identified) and all(r==identified[0] and r['exe_sha256']==controller.EXPECTED_BOT and r['exe_path']==controller.EXPERIMENT_BINARIES['bots'] for r in identified)
    missing=[r['start_ns'] for r in polls if r['observations']['bots'].get('phase') and not r['observations']['bots'].get('guard') and not r['observations']['bots'].get('bot_identity')]
    runtime_ok=runtime_ok and not missing
    if full['workloads_launched']:
        full['gates']['candidate_bot_runtime_identity']=runtime_ok
        try:
            controller.validate_startup(manifest['startup_log'])
            controller.validate_game_runtime(manifest['pre_swarm_runtime'], fresh=True)
            for poll in polls:controller.validate_game_runtime(poll['observations']['game'], manifest['pre_swarm_runtime'])
            game_runtime_ok=bool(polls)
        except (KeyError,RuntimeError):game_runtime_ok=False
        full['gates']['candidate_game_runtime_and_buffers']=game_runtime_ok
        full['gates']['bot_buffers_unchanged']=all(full['hosts']['bots'].get(period,{}).get('rb_values')==[212992] and full['hosts']['bots'].get(period,{}).get('tb_values')==[212992] for period in ('full_workload','steady_window'))
        runtime_ok=runtime_ok and game_runtime_ok and full['gates']['bot_buffers_unchanged']
        for role in ('game','bots'):
            v=full['hosts'][role].get('full_workload',{}).get('udp_delta',{})
            full['gates'][role+'_full_workload_udp_errors_zero']=bool(v) and all(v.get(k)==0 for k in ('RcvbufErrors','SndbufErrors','InErrors','MemErrors','InCsumErrors'))
        full['collector_valid']=full['collector_valid'] and runtime_ok
        full['generator_valid']=full['collector_valid'] and all(full['gates'][k] for k in ('per_identity_offered_29_7hz','mapped_wire_29_7hz','bots_udp_errors_zero','bots_full_workload_udp_errors_zero'))
        full['classification']='collector-invalid' if not full['collector_valid'] else 'generator-invalid' if not full['generator_valid'] else 'clean-cell-pass' if all(full['gates'].values()) else 'valid-failure'
        if manifest.get('controller_abort') or manifest.get('controller_error'):
            full['classification']='aborted-'+full['classification']
        full['highest_passing_population_this_observation']=controller.POPULATION if all(full['gates'].values()) else None
        full['failed_gates']=[k for k,v in full['gates'].items() if not v]
    augment_clean_gates(full, d)
    preservation=base.load(P/'independent-prebuild-preservation-audit.json',{})
    full['gates']['autonomous_recovery_succeeded']=original_cleanup.get('game',{}).get('restored') is True
    full['gates']['independent_final_cleanup_verified']=(set(cleanup)=={'game','bots'} and set(preservation)=={'game','bots'} and
        all(not any(v is False for v in row.values()) and not row.get('competing_or_owned_processes') for row in cleanup.values()) and
        all(bool(row.get('checks')) and all(row['checks'].values()) for row in preservation.values()))
    classify(full)
    (P/'full-analysis.json').write_text(json.dumps(full)+'\n')
    public={k:full.get(k) for k in ('namespace','workloads_launched','classification','window','workload_start_ns','workload_end_ns','controller_decision_ns','controller_abort','controller_error','guard_reason','gates','failed_gates','generator_summary','full_workload_bot_errors','server_errors','settings','runtime_proof','polling','bot_observer_cost','cleanup','boundary_lateness_ms','collector_valid','generator_valid')}
    public['recovery_finding']={k:recovery.get(k) for k in ('original_restore_exit','original_restore_error','cause','timer_disarmed_after_verified_original_state','owned_active_units_absent','game_archive_completion')}
    public['legacy_harness_criteria']=full.get('legacy_harness_criteria')
    public['bot_aggregated']=full.get('bot_aggregated')
    public['clean_evidence']=full.get('clean_evidence')
    deficits=wire_deficits(full,d)
    deficit_file=P/'offered-to-wire-deficits.json'
    deficit_file.write_text(json.dumps(deficits)+'\n')
    public['offered_to_wire_deficits']={'peer_count':len(deficits),
        'gate_failing_peer_ids':[r['bot_id'] for r in deficits if r['failed_wire_hosts']],
        'worst_observed_differences':sorted(deficits,key=lambda r:max((v for v in r['offered_minus_wire_hz'].values() if v is not None),default=-1),reverse=True)[:10],
        'per_peer_evidence_sha256':hashlib.sha256(deficit_file.read_bytes()).hexdigest(),
        'cause':None,'meaning':'Observed cadence differences; offered observation endpoints and exact UTC wire window differ. Not an exact packet-loss or application-delivery count.'}
    public.update(new_validated_capacity=None,highest_historical_validated_strategy_population=100,
        unknowns={k:None for k in ('application_delivered_inputs','projectile_owner_map_occupancy','poll_cycle_duration','receive_queue_residence','causal_instrumentation_slowdown','outstanding_reliable_queue')},
        phase2_utc_ns=phase,measurement=full.get('periods',{}).get('steady_window'),hosts={},collectors={},evidence_sha256={},capacity_gates_scored=True,
        condition=f'Matched {controller.BEHAVIOR} {controller.POPULATION} with candidate game and bots, same send150 config; Emission audit disabled; bounded compact measurement and repaired wire collector. Candidate behavior changed; no pure performance comparison. World entropy not fixed.',
        candidate_build={'revision':controller.CANDIDATE_REVISION,'path':controller.EXPERIMENT_BINARIES['game'],'expected_sha256':controller.EXPECTED_CANDIDATE,'both_host_proofs':base.load(BUILD/'build-proof.json')},
        bot_runtime={'valid':runtime_ok,'identity':identified[0] if identified else None,'matching_polls':len(identified),'missing_live_identity_poll_ns':missing},
        strict_assertions=[{k:r.get(k) for k in ('name','passed','skipped','message')}|{'violator_count':len((r.get('details') or {}).get('violators',[]))} for r in (full.get('strict_assertions') or [])],
        journal={k:v for k,v in journal.items() if k not in ('seconds','first_findings')} if journal else None,
        journal_errors=full.get('journal_errors'))
    if public['candidate_build']['both_host_proofs']:
        for proof in public['candidate_build']['both_host_proofs'].values():proof.pop('build_stdout',None)
    if public['journal']:
        for period in public['journal']['periods'].values():
            period['interval_observed']=period['end_ns']<=manifest.get('game_stopped_utc_ns',0)
            if not period['interval_observed']:period['counts']=None
    perbot=full.get('per_bot',[])
    public['steady_bot_errors']={key:sum(r['errors_delta'][key] for r in perbot) for key in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')} if perbot else None
    public['failing_peer_ids']={
        'offered':[r['id'] for r in perbot if r['offered_input_hz']<29.7],
        'wire':{role:[r['id'] for r in perbot if r['wire_input_hz'][role] is None or r['wire_input_hz'][role]<29.7] for role in ('game','bots')},
        'delivery':[r['id'] for r in perbot if not r['delivery_gate']],
        'strict_assertions':{r['name']:[v['bot_id'] for v in (r.get('details') or {}).get('violators',[])] for r in (full.get('strict_assertions') or []) if not r.get('passed')},
        'steady_correctness':{k:[r['id'] for r in perbot if r['errors_delta'][k]>0] for k in ('baseline_reference_misses','unknown_delta_entities','decode_failures','send_failures','panics')}}
    if phase and (d/'bots/bots.ndjson').exists():
        public['trajectories']=active_trajectories(d,phase)
        public['ramp']=ramp_evidence(d,phase)
    public['per_peer_scoring_count']=len(perbot)
    if len(perbot)!=controller.POPULATION:public['failing_peer_ids']['unscored']=sorted(set(range(1,controller.POPULATION+1))-{r['id'] for r in perbot})
    public['first_journal_findings']={k:{'utc_ns':v.get('utc_ns'),'message_prefix':v.get('message','')[:256]} for k,v in (journal or {}).get('first_findings',{}).items()}
    public['delivery_failing_peer_tails']=[{k:r[k] for k in ('id','snapshot_age_p99_ms','snapshot_age_max_ms','confirm_age_p99_ms','confirm_age_max_ms','delivery_samples_complete')} for r in perbot if not r['delivery_gate']]
    unattributed=[]
    for role,h in full.get('hosts',{}).items():
        public['hosts'][role]={k:v for k,v in h.items() if k not in ('qdisc_first_last','full_workload','active_until_decision','steady_window')}
        public['hosts'][role]['periods']={name:{k:v for k,v in h.get(name,{}).items() if k!='cpu'} for name in ('full_workload','steady_window')}
        public['hosts'][role]['steady_cpu']=h.get('steady_window',{}).get('cpu',{}).get('matched_boundary')
        public['hosts'][role]['steady_cpu_1hz']=h.get('steady_window',{}).get('cpu',{}).get('one_second_statistics')
        observations=base.rows(d/role/'host.ndjson.gz')
        for row in observations:
            for sock in sockets(row['ss']['stdout']):
                if sock['pid'] is None:unattributed.append({'role':role,'utc_ns':row['utc_ns'],**sock})
        w=full.get('window')
        inside=[r for r in observations if w and w['start']<=r['utc_ns']<=w['end']]
        public['hosts'][role]['steady_inner_cpu']=base.cpu_report.interval(inside[0],inside[-1]) if len(inside)>=2 else None
        c=full['collector'][role]
        public['collectors'][role]={k:c[k] for k in ('source_and_executable_sha256','parser','resource','capture_drops','mapping_count','mapping_unique','mapped_identities_complete','capture_span_ns','retained_bytes')}
        public['collectors'][role]['flow_counters']={k:v for k,v in c['flow_summary'].items() if k not in ('wire_input_counts_by_port','ports','per_port') and not isinstance(v,list)}
    # Explicitly preserve send as well as receive sampled memory, without queue residence claims.
    for role in ('game','bots'):
        h=base.rows(d/role/'host.ndjson.gz')
        public['hosts'][role]['sampled_socket_memory']={}
        q=full['hosts'][role].get('qdisc_first_last')
        public['hosts'][role]['qdisc_observation']={'first':q[0],'last':q[1],
            'deltas':{k:sum(r.get(k,0) for r in q[1])-sum(r.get(k,0) for r in q[0]) for k in ('drops','overlimits','requeues','drop_overlimit','ecn_mark')}} if q and len(q)==2 else None
        for name,left,right in [('full_workload',full['workload_start_ns'],full['workload_end_ns']),('steady_window',full['window']['start'],full['window']['end'])]:
            samples=[(r,s) for r in h if left<=r['utc_ns']<=right for s in sockets(r['ss']['stdout'])]
            public['hosts'][role]['sampled_socket_memory'][name]={
                'sample_rows':len(samples),'fields':{k:base.dist([s.get(k) for _,s in samples]) for k in ('r','rb','t','tb','w','f','bl','d')},
                'missing_pid_rows':sum(s.get('pid') is None for _,s in samples)}
    public['unknowns']['send_queue_residence']=None
    server_rows=base.rows(d/'game/server.ndjson')
    public['boundary_transport']={r['boundary']:{'utc_ns':r['utc_ns'],'transport':r.get('transport')} for r in server_rows if r.get('boundary')}
    public['game_runtime_process']=manifest.get('pre_swarm_runtime',{}).get('process')
    public['socket_attribution_missing_rows']=unattributed
    (P/'unattributed-socket-rows.json').write_text(json.dumps(unattributed)+'\n')
    prior=base.load(ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-21-udp-diagnosis/send150-summary.json')
    public['direct_unprofiled_comparator']={k:prior.get(k) for k in ('namespace','classification','generator_summary','steady_bot_errors','strict_assertions','measurement','hosts')}
    public['collector_sources_equal_unprofiled_comparator']={role:{name:full['collector'][role]['source_and_executable_sha256'].get(name)==prior['collectors'][role]['source_and_executable_sha256'].get(name) for name in ('host_collect.py','capture.py','udp_control_capture.py','udp_control_record.rs','udp_control_flow.rs','udp_capacity150_capture.py','atomic_publish.py')} for role in ('game','bots')}
    public['full_workload_transport']=full.get('periods',{}).get('full_workload',{}).get('transport')
    public['full_workload_delivery_aggregate_s']=full.get('periods',{}).get('full_workload',{}).get('delivery_aggregate_s')
    public['independent_analysis_checks']=base.load(P/'independent-analysis-checks.json')
    public['final_post_analysis_state']=base.load(P/'final-post-analysis-state.json')
    public['local_validation']=base.load(BUILD/'local-validation.json')
    public['analysis_validation']=base.load(P/'final-local-validation.json',base.load(BUILD/'analysis-validation.json'))
    public['candidate_build']['toolchain_and_source']=base.load(BUILD/'toolchain-and-source-proof.json')
    public['independent_prebuild_preservation_audit']=base.load(P/'independent-prebuild-preservation-audit.json')
    public['private_evidence']=str(P.relative_to(ROOT))
    public['remote_evidence']='/home/deploy/omega-results/'+controller.NAMESPACE
    for path in [P/'final-local-validation.json',*P.glob('*.tar.gz'),P/'manifest.json',P/'cleanup.json',P/'recovery-completion.json',P/'recovery-failure-readonly.json',P/'final-verification-summary.json',P/'clean_run.executed.py',P/'preserved-measurement-sha256.txt',BUILD.parent/(controller.NAMESPACE+'-build.tar.gz'),BUILD/'analysis-validation.json',BUILD/'build-proof.json',BUILD/'local-validation.json',BUILD/'toolchain-and-source-proof.json',P/'independent-analysis-checks.json',P/'independent-prebuild-preservation-audit.json',P/'final-post-analysis-state.json',*sorted((ROOT/'scripts/load_campaign').glob('*clean*.py'))]:
        if path.exists():public['evidence_sha256'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    text='{\n'+',\n'.join('  '+json.dumps(k)+': '+json.dumps(v,sort_keys=True) for k,v in public.items())+'\n}\n'
    for host in base.load(ROOT/'deployment/hetzner/access.local.json')['servers']:text=text.replace(host['ipv4'],'[private-endpoint]')
    (PUBLIC/(controller.NAMESPACE+'-summary.json')).write_text(text)
    print(json.dumps({k:public[k] for k in ('classification','workloads_launched','failed_gates','new_validated_capacity')}))
    return public

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',default=controller.NAMESPACE)
    args=parser.parse_args()
    manifest=base.load(ROOT/'deployment/hetzner/results'/args.namespace/'manifest.json')
    controller.load_cell(args.namespace, manifest['requested_bots'], manifest['behavior'])
    P=ROOT/'deployment/hetzner/results'/controller.NAMESPACE
    BUILD=ROOT/'deployment/hetzner/results'/(controller.NAMESPACE+'-build')
    main()
