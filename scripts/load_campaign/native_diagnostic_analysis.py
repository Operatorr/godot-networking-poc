#!/usr/bin/env python3
"""Offline native retirement/socket/capture reconciliation on real isolated extraction.

Retains exact clock-window differences. Handoff != network arrival != application delivery.
Raw input records contain numeric metadata/fingerprint only, never payload or Debug text.
"""
import collections
import csv
import hashlib
import json
import pathlib
import struct

RECORD=struct.Struct('<QQQQQIIIIII')
DATAGRAM=struct.Struct('<QHHHHQH')
ERRORS=('trace_limit','pending_limit','write_errors','untracked_retirement','whitelist_errors',
        'parser_errors','duplicate_input_attempt','unmatched_socket_input','socket_zero',
        'socket_partial','socket_errors','receive_errors','receive_partial','service_errors')

def read_records(path):
    data=path.read_bytes()
    if len(data)%RECORD.size or len(data)>16384*64:raise ValueError('Native trace truncated/oversized')
    return list(RECORD.iter_unpack(data))

def capture_timestamps(path, known):
    result=collections.defaultdict(list)
    with path.open('rb') as stream:
        if stream.read(4)!=b'ORF1':raise ValueError('Capture magic')
        while raw:=stream.read(DATAGRAM.size):
            if len(raw)!=DATAGRAM.size:raise ValueError('Capture record truncation')
            stamp,source,target,ip_len,udp_len,fingerprint,commands=DATAGRAM.unpack(raw)
            if commands:raise ValueError('Expected compact v2 capture')
            key=(source,fingerprint)
            if target==8081 and key in known:result[key].append(stamp)
    return result


def capture_inputs(path, known, window=None):
    counts={key:sum(window is None or window[0]<=stamp<window[1] for stamp in stamps)
            for key,stamps in capture_timestamps(path,known).items()}
    return collections.Counter({k:n for k,n in counts.items() if n})


def fingerprint_timing(native, captured, port, window):
    stamps=collections.defaultdict(list)
    for attempt,fingerprint in set((r[2],r[4]) for r in native if r[4]%64==0):
        stamps[(port,fingerprint)].append(attempt)
    offsets=[];crossings=[];unpaired=0
    start,end=window
    for key,attempts in stamps.items():
        seen=sorted(captured.get(key,[]));attempts.sort()
        unpaired+=abs(len(seen)-len(attempts))
        for sent,stamp in zip(attempts,seen):
            offsets.append(stamp-sent)
            if (start<=sent<end)!=(start<=stamp<end):
                crossings.append(dict(fingerprint=key[1],native_ns=sent,capture_ns=stamp,
                                      native_in_window=start<=sent<end,capture_in_window=start<=stamp<end))
    offsets.sort()
    return dict(paired_sampled_datagrams=len(offsets),unpaired_sampled_datagrams=unpaired,
                capture_minus_native_ns=dict(min=min(offsets,default=None),max=max(offsets,default=None),
                    p99=offsets[(len(offsets)*99+99)//100-1] if offsets else None),
                exact_window_membership_differences=crossings)


def throttle_trace_classification(records):
    """The native classifier uses pre-throttle. Independently require equality.

    A pre/post throttle change makes the counter/predicate causal witness ambiguous;
    retain those events rather than silently treating the native label as proof.
    """
    no_attempt=[r for r in records if r[9]==5]
    single=[r for r in no_attempt if r[5]<=32 and r[6]<32 and
            r[8]==(r[6]+7)%32 and r[8]>r[5]]
    stable=[r for r in single if r[5]==r[7]]
    ambiguous=[dict(ordinal=r[3],admission_ns=r[0],retirement_ns=r[1],
                    pre_throttle=r[5],post_throttle=r[7],pre_counter=r[6],post_counter=r[8],
                    reason='throttle-changed' if r in single else 'no-single-step-predicate-witness')
               for r in no_attempt if r not in stable]
    return dict(no_attempts=len(no_attempt),single_step_pre_predicate=len(single),
                stable_throttle_single_step=len(stable),
                throttle_changed=sum(r[5]!=r[7] for r in no_attempt),ambiguous=ambiguous)

def analyze(directory, manifest):
    d=pathlib.Path(directory)
    if any(p.is_symlink() or (p.is_file() and p.stat().st_nlink!=1) for p in d.rglob('*')):
        raise ValueError('Analysis requires real isolated copies')
    observations=[json.loads(line) for line in (d/'bots/bots.ndjson').read_text().splitlines()]
    final={b['id']:b['native_diagnostic'] for b in observations[-1]['bots']}
    mappings={}
    lifetime_capture={}
    for role in ('game','bots'):
        with (d/role/'port-bot.csv').open() as stream:
            mappings[role]={int(r['bot_id']):int(r['port']) for r in csv.DictReader(stream)}
        with (d/role/'input-ports.csv').open() as stream:
            counts=collections.Counter()
            for row in csv.DictReader(stream):counts[int(row['port'])]+=int(row['input_commands'])
            lifetime_capture[role]=counts
    population=manifest['requested_bots']; start,end=(manifest['window'][k] for k in ('start','end'))
    checks={'identity_map_complete':mappings['game']==mappings['bots'] and set(mappings['bots'])==set(range(1,population+1)),
            'final_diagnostic_complete':set(final)==set(range(1,population+1)) and all(isinstance(v,dict) and v.get('schema')==1 for v in final.values())}
    if not all(checks.values()):return dict(checks=checks,evidence_complete=False)
    peers=[];fingerprints=collections.Counter();cost=0;errors=collections.Counter();total=collections.Counter()
    evidence={}
    for i,diag in sorted(final.items()):
        path=d/'bots'/f'native-{i}.bin';records=read_records(path);c=diag['counts'];counts=collections.Counter(r[9] for r in records)
        native=[r for r in records if r[9]==1]
        window=[r for r in native if start<=r[2]<end]
        for attempt,fingerprint in set((r[2],r[4]) for r in native if r[4]%64==0):
            fingerprints[mappings['bots'][i],fingerprint]+=1
        error={k:c.get(k,0) for k in ERRORS};errors.update(error);cost+=diag['completed_observer_ns']
        full=dict(created=c.get('created',0),admitted=c.get('admitted',0),retired=len(records),socket_input_handoffs=len(native),
            socket_input_attempts=sum(r[9] in (1,2,3,4) for r in records),
            socket_all_datagram_attempts=c.get('socket_attempts',0),socket_all_datagram_handoffs=c.get('socket_handoffs',0),
            no_attempt=counts[5],zero=counts[2],partial=counts[3],error=counts[4],pending=diag['pending_inputs'],
            throttle_witness=c.get('no_attempt_single_step_throttle_witness',0),unclassified=c.get('no_attempt_unclassified',0))
        interval=dict(admitted=sum(start<=r[0]<end for r in records),handoffs=len(window),
            no_attempt_admissions=sum(start<=r[0]<end and r[9]==5 for r in records),
            carried_in=sum(r[0]<start and start<=r[2]<end for r in native),
            carried_out=sum(start<=r[0]<end and r[2]>=end for r in native),
            pending_at_start=sum(r[0]<start<=r[1] for r in records),pending_at_end=sum(r[0]<end<=r[1] for r in records))
        expected=interval['no_attempt_admissions']+interval['carried_out']-interval['carried_in']
        # This identity accounts for admission-to-socket differences within one clock domain.
        accounting=(interval['admitted']-interval['handoffs']==expected and full['pending']==0 and
            full['created']==full['admitted']==len(records)==c.get('retired',0) and full['socket_input_handoffs']==c.get('socket_input_handoffs',0) and
            full['socket_input_attempts']==c.get('socket_input_attempts',0) and
            full['throttle_witness']+full['unclassified']==full['no_attempt'] and
            all(r[3]==n and r[0]<=r[1] and
                (r[0]<=r[2]<=r[1] if r[9] in (1,2,3,4) else r[2]==r[4]==0)
                for n,r in enumerate(records,1)) and diag['trace_records']==len(records))
        throttle=throttle_trace_classification(records)
        cap={role:json.loads((d/role/'flow-summary.json').read_text())['wire_input_counts_by_port'].get(str(mappings[role][i]),0) for role in ('game','bots')}
        peer=dict(id=i,full=full,window=interval,capture_window=cap,
            capture_lifetime_input_commands={role:lifetime_capture[role][mappings[role][i]] for role in mappings},
            lifetime_handoff_minus_capture={role:len(native)-lifetime_capture[role][mappings[role][i]] for role in mappings},
            native_minus_capture={role:len(window)-n for role,n in cap.items()},
            native_attempts_within_10ms_of_boundary=sum(any(abs(r[2]-t)<=10_000_000 for t in (start,end)) for r in native),
            throttle_min=diag['throttle_min'],raw_single_counter_witnesses=throttle['single_step_pre_predicate'],
            independent_throttle_trace=throttle,
            trace_times=dict(first_admission_ns=min((r[0] for r in records),default=None),
                last_admission_ns=max((r[0] for r in records),default=None),
                last_retirement_ns=max((r[1] for r in records),default=None),
                first_handoff_ns=min((r[2] for r in native),default=None),
                last_handoff_ns=max((r[2] for r in native),default=None)),
            native_outgoing_queue_length=diag['native_outgoing_queue_length'],
            native_reliable_queue_length=diag['native_reliable_queue_length'],
            native_receive_truncation_detection=diag['native_receive_truncation_detection'],
            max_retirement_age_ns=diag['max_input_retirement_age_ns'],max_service_gap_ns=diag['max_service_gap_ns'],
            max_service_bracket_ns=diag['max_service_bracket_ns'],last_numeric_peer=diag['last_numeric_peer'],
            accounting=accounting,trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),trace_bytes=path.stat().st_size)
        peers.append(peer);total.update(full)
    capture_times={role:capture_timestamps(d/role/'datagrams.bin',fingerprints) for role in ('game','bots')}
    capture={role:collections.Counter({k:len(v) for k,v in raw.items()}) for role,raw in capture_times.items()}
    window_capture={role:collections.Counter({k:sum(start<=t<end for t in v) for k,v in raw.items()}) for role,raw in capture_times.items()}
    for peer in peers:
        port=mappings['bots'][peer['id']]
        records=read_records(d/'bots'/f"native-{peer['id']}.bin")
        native=[r for r in records if r[9]==1]
        sampled=collections.Counter((port,fp) for at,fp in set((r[2],r[4]) for r in native if r[4]%64==0))
        sampled_window=collections.Counter((port,fp) for at,fp in set((r[2],r[4]) for r in native if r[4]%64==0 and start<=r[2]<end))
        def reconciliation(expected,actual):
            selected=collections.Counter({k:v for k,v in actual.items() if k[0]==port})
            return dict(native_sampled_input_datagrams=sum(expected.values()),capture_records=sum(selected.values()),
                        missing=sum((expected-selected).values()),extra=sum((selected-expected).values()))
        peer['sampled_fingerprint_reconciliation']={role:dict(
            full=reconciliation(sampled,capture[role]),
            exact_window=reconciliation(sampled_window,window_capture[role]),
            timing=fingerprint_timing(native,capture_times[role],port,(start,end))) for role in capture}
    matched={role:dict(native_sampled_input_datagrams=sum(fingerprints.values()),capture_matched=sum(capture[role].values()),
        missing=sum((fingerprints-capture[role]).values()),extra=sum((capture[role]-fingerprints).values())) for role in capture}
    checks.update(all_native_accounting=all(p['accounting'] for p in peers),all_observer_and_socket_error_counters_zero=not any(errors.values()),
        all_no_attempts_have_single_step_throttle_witness=total['no_attempt']==total['throttle_witness'] and total['unclassified']==0 and all(p['raw_single_counter_witnesses']==p['full']['no_attempt'] for p in peers),
        all_no_attempt_trace_throttles_unchanged=all(not p['independent_throttle_trace']['ambiguous'] for p in peers),
        lifetime_handoffs_equal_both_complete_capture_counts=all(delta==0 for p in peers for delta in p['lifetime_handoff_minus_capture'].values()),
        sampled_fingerprints_match_both_captures=all(v['missing']==v['extra']==0 for v in matched.values()),
        capture_count_differences_bounded_by_boundary_candidates=all(abs(delta)<=p['native_attempts_within_10ms_of_boundary'] for p in peers for delta in p['native_minus_capture'].values()))
    return dict(schema=2,checks=checks,evidence_complete=all(checks.values()),full=dict(total),errors=dict(errors),peers=peers,
        window=dict(start_ns=start,end_ns=end,duration_ns=end-start),
        final_observation_utc_ns=observations[-1]['utc_ns'],
        fingerprint_sample_modulus=64,
        retirement_timestamp_semantics='Post-service record write observes tracked-buffer retirement; it is not the exact Drop instant. Boundary pending counts are inferred from these timestamp brackets. Final pending count is directly observed. Native queue lengths are unavailable.',
        sampled_fingerprint_reconciliation=matched,completed_observer_ns=cost,
        record_bytes=sum(p['trace_bytes'] for p in peers),
        semantics='Native attempts timestamped immediately before unchanged Socket::send; successful full-length returns are socket handoffs. Native/capture windows use different clock sources and capture timestamps have microsecond resolution. Whole-run sampled full-UDP fingerprints are matched independently of the collector command parser. Exact application delivery remains unknown. Pending input-buffer lifecycle is measured; native queue lengths and reliable queue occupancy remain unknown. Instrumentation cost is measured internally and may alter overhead; no historical causal attribution follows.')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=pathlib.Path);parser.add_argument('manifest',type=pathlib.Path);parser.add_argument('output',type=pathlib.Path)
    args=parser.parse_args();result=analyze(args.directory,json.loads(args.manifest.read_text()))
    with args.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps({k:result[k] for k in ('checks','evidence_complete','full')}))
