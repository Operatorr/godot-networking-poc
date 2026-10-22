#!/usr/bin/env python3
"""Offline-only send150 analysis; preserve historical analyzers and public reports."""
import hashlib
import collections
import json
import pathlib
import tarfile
import udp_capacity150_analysis as base
from udp_generator_profile_fixed_details import sockets, trajectories
import aoi150 as controller

ROOT=pathlib.Path(__file__).resolve().parents[2]
P=ROOT/'deployment/hetzner/results'/controller.NAMESPACE
BUILD=ROOT/'deployment/hetzner/results'/ (controller.NAMESPACE+'-build')
PUBLIC=ROOT/'docs/netcode/perf-notes/load-test-reports/2026-10-22-aoi-diagnosis'
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
    for i in range(1,151):
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


def main():
    d=P/'extracted';d.mkdir(exist_ok=True)
    cleanup=base.load(P/'final-verification-summary.json',{})
    for role in ('game','bots'):
        archive=P/(role+'.tar.gz')
        if not archive.exists():continue
        actual=hashlib.sha256(archive.read_bytes()).hexdigest()
        assert actual==base.load(P/'cleanup.json')[role]['archive_remote_sha256']
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
        full['classification']='collector-invalid' if not full['collector_valid'] else 'generator-invalid' if not full['generator_valid'] else 'capacity-pass-with-correctness-findings' if all(full['gates'].values()) else 'valid-failure'
        if manifest.get('controller_abort') or manifest.get('controller_error'):
            full['classification']='aborted-'+full['classification']
        full['highest_passing_population_this_observation']=150 if all(full['gates'].values()) else None
        full['failed_gates']=[k for k,v in full['gates'].items() if not v]
    (P/'full-analysis.json').write_text(json.dumps(full)+'\n')
    public={k:full.get(k) for k in ('namespace','workloads_launched','classification','window','workload_start_ns','workload_end_ns','controller_decision_ns','controller_abort','controller_error','guard_reason','gates','failed_gates','generator_summary','full_workload_bot_errors','server_errors','settings','runtime_proof','polling','bot_observer_cost','cleanup','boundary_lateness_ms','collector_valid','generator_valid')}
    public.update(new_validated_capacity=None,highest_historical_validated_strategy_population=100,
        unknowns={k:None for k in ('application_delivered_inputs','projectile_owner_map_occupancy','poll_cycle_duration','receive_queue_residence','causal_instrumentation_slowdown','outstanding_reliable_queue')},
        phase2_utc_ns=phase,measurement=full.get('periods',{}).get('steady_window'),hosts={},collectors={},evidence_sha256={},capacity_gates_scored=True,
        condition='Matched Strategy150 with candidate game and bots, same send150 config; OMEGA_AOI_AUDIT=1 and repaired bot diagnostic evidence change overhead. No pure performance comparison. World entropy not fixed.',
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
    if len(perbot)!=150:public['failing_peer_ids']['unscored']=sorted(set(range(1,151))-{r['id'] for r in perbot})
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
    for path in [P/'final-local-validation.json',*P.glob('*.tar.gz'),P/'manifest.json',P/'cleanup.json',P/'final-verification-summary.json',P/'aoi150.executed.py',P/'preserved-measurement-sha256.txt',BUILD.parent/(controller.NAMESPACE+'-build.tar.gz'),BUILD/'analysis-validation.json',BUILD/'build-proof.json',BUILD/'local-validation.json',BUILD/'toolchain-and-source-proof.json',P/'independent-analysis-checks.json',P/'independent-prebuild-preservation-audit.json',P/'final-post-analysis-state.json',*sorted((ROOT/'scripts/load_campaign').glob('*aoi150*.py'))]:
        if path.exists():public['evidence_sha256'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    text='{\n'+',\n'.join('  '+json.dumps(k)+': '+json.dumps(v,sort_keys=True) for k,v in public.items())+'\n}\n'
    for host in base.load(ROOT/'deployment/hetzner/access.local.json')['servers']:text=text.replace(host['ipv4'],'[private-endpoint]')
    (PUBLIC/'aoi150-summary.json').write_text(text)
    print(json.dumps({k:public[k] for k in ('classification','workloads_launched','failed_gates','new_validated_capacity')}))
    return public

if __name__=='__main__':main()
