"""Explainable time/spend admission over the legal remaining search paths (issue #61 §1).

Admission is recomputed from the frozen manifest, the journaled search state and an injected
clock before the first provider mutation, before every dispatch and before any explicit
resume. It never calls a provider. A rejection therefore creates nothing.

Time model (seconds), all terms from the manifest or the accepted contract:

  pre-workload  = create_bootstrap + readiness_access             (until verified pair-ready)
  per trial     = readiness_bound(N) + 2 s warmup + hold + process_reset
                  + recorder_finalization + per_trial_export
  tail          = collection_export + evidence_recovery_grace
  C             = max_session_duration - teardown_reserve          (workloads/recovery end by C)

  fit  <=>  elapsed + pre-workload(remaining) + max over legal paths(sum per trial) + tail  <=  C

The nominal ramp lives inside readiness_bound(N) = max(60, N*0.1 + 30) and is not added again.

Cost model: both hosts for the FULL duration cap (the watchdog may need every second of it),
hourly price x billable units (increment + minimum), plus conservative outbound transfer with
the allowance prorated by cap/730 h when enabled, at the overage price. The management host's
recurring cost is disclosed separately and is not part of the session estimate.
"""
import dataclasses
import datetime
import math

import manifest as manifest_mod
import search

ADMITTED = 'admitted'
REJECTED = 'rejected'
NO_REMAINING_WORK = 'no_remaining_work'


@dataclasses.dataclass
class Admission:
    decision: str
    reasons: list
    evaluated_at: str
    manifest_sha256: str
    time: dict
    cost: dict
    search: dict
    next_run: dict

    @property
    def admitted(self):
        return self.decision == ADMITTED

    def to_dict(self):
        return dataclasses.asdict(self)


def parse_utc(text):
    stamp = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp must carry a UTC offset: ' + str(text))
    return stamp.astimezone(datetime.timezone.utc)


def trial_duration(manifest, trial):
    """Per-term duration of one trial; every term is named so the explanation is checkable."""
    timing = manifest['timing_basis']
    terms = dict(
        readiness_bound_s=search.readiness_bound_s(trial.target),
        post_auth_warmup_s=search.POST_AUTH_WARMUP_S,
        hold_s=trial.hold_s,
        process_reset_s=timing['process_reset_s']['seconds'],
        recorder_finalization_s=timing['recorder_finalization_s']['seconds'],
        per_trial_export_s=timing['per_trial_export_s']['seconds'],
    )
    return dict(run_id=trial.run_id, target=trial.target, phase=trial.phase, terms=terms,
                nominal_ramp_s=search.nominal_ramp_s(trial.target),
                note='nominal ramp is inside readiness_bound_s and not counted again',
                total_s=sum(terms.values()))


def path_cost(manifest, path):
    trials = [trial_duration(manifest, t) for t in path]
    return dict(trials=trials, total_s=sum(t['total_s'] for t in trials),
                scored_hold_s=sum(t.hold_s for t in path), count=len(path),
                run_ids=[t.run_id for t in path])


def _billable_units(duration_s, pricing):
    increment = pricing['billing_increment_s']
    minimum = pricing['billing_minimum_s']
    return max(math.ceil(duration_s / increment), math.ceil(minimum / increment))


def estimate_cost(manifest):
    """Both hosts for the full cap plus conservative transfer; management host separate."""
    pricing = manifest['pricing']
    limits = manifest['limits']
    cap_s = limits['max_session_duration_s']
    roles = {}
    compute_total = transfer_total = transfer_gib_total = 0.0
    for role in ('game', 'bot'):
        quote = manifest['quote']['roles'][role]
        units = _billable_units(cap_s, pricing)
        compute = units * quote['price_hourly_usd'] * (pricing['billing_increment_s'] / 3600.0)
        estimated_gib = float(pricing['estimated_outbound_gib'][role]['gib'])
        allowance_gib = 0.0
        if pricing['prorate_transfer_allowance']:
            allowance_gib = quote['transfer_tib_month'] * 1024.0 * (cap_s / 3600.0) / pricing['allowance_hours_per_month']
        overage_gib = max(0.0, estimated_gib - allowance_gib)
        transfer = overage_gib * pricing['transfer_overage_usd_per_gib']
        roles[role] = dict(size_slug=quote['size_slug'], price_hourly_usd=quote['price_hourly_usd'],
                           billed_for_s=cap_s, billable_units=units,
                           billing_increment_s=pricing['billing_increment_s'],
                           billing_minimum_s=pricing['billing_minimum_s'], compute_usd=round(compute, 6),
                           estimated_outbound_gib=estimated_gib,
                           outbound_basis=pricing['estimated_outbound_gib'][role]['basis'],
                           prorated_allowance_gib=round(allowance_gib, 6), overage_gib=round(overage_gib, 6),
                           transfer_usd=round(transfer, 6))
        compute_total += compute
        transfer_total += transfer
        transfer_gib_total += estimated_gib
    session_total = compute_total + transfer_total
    return dict(
        quote_observed_at=manifest['quote']['observed_at'], roles=roles,
        compute_usd=round(compute_total, 6), transfer_usd=round(transfer_total, 6),
        estimated_outbound_gib=round(transfer_gib_total, 6),
        session_estimate_usd=round(session_total, 6),
        max_estimated_session_usd=limits['max_estimated_session_usd'],
        max_estimated_transfer_gib=limits['max_estimated_transfer_gib'],
        management_host_monthly_usd_separate=pricing['management_host_monthly_usd'],
        assumptions=[
            'both hosts billed for the full duration cap, not the expected lifetime',
            'billing increment/minimum from pricing provenance: ' + str(pricing['provenance']),
            'transfer allowance ' + ('prorated by cap/allowance_hours_per_month' if pricing['prorate_transfer_allowance']
                                     else 'not credited at all'),
            'management-host recurring cost is disclosed separately, not added here',
            'this is an admission estimate, never an invoice or a provider billing ceiling',
        ])


def _check_health(infra_health, sha, reasons):
    if not isinstance(infra_health, dict):
        reasons.append('cleanup infrastructure health is unknown: registry/watchdog status absent')
        return
    for component in ('registry', 'watchdog'):
        status = infra_health.get(component) or {}
        if status.get('healthy') is not True:
            reasons.append(component + ' is not reported healthy; unhealthy cleanup infrastructure rejects admission')
        if status.get('acknowledged_manifest_sha256') != sha:
            reasons.append(component + ' has not acknowledged this exact manifest hash')


def admit(manifest, recorded_sha256, state, now, infra_health, phase='pre_create', t0=None,
          resume_requested=False, current_limits=None):
    """Evaluate admission for the legal remaining work.

    ``phase`` is 'pre_create', 'provisioning' (t0 recorded but readiness not proven), or
    'pair_ready' (bootstrap/readiness already spent). ``t0`` is the UTC instant immediately
    before the first create request. Provisioning conservatively retains the full setup
    bound until explicit readiness evidence establishes that setup is complete.
    ``current_limits`` lets a caller prove the limits in force are the manifest's; any
    difference is a changed contract and rejects.
    """
    reasons = []
    evaluated_at = parse_utc(now)
    try:
        sha = manifest_mod.verify_manifest(manifest, recorded_sha256)
    except manifest_mod.ManifestError as error:
        return Admission(REJECTED, error.reasons, evaluated_at.isoformat(), recorded_sha256,
                         {}, {}, {}, None)
    if manifest['session']['kind'] != 'capacity':
        reasons.append('capacity search is unavailable for ' + str(manifest['session']['kind']) +
                       ': calibration and lifecycle smoke require separate bounded workload plans')
    if current_limits is not None and current_limits != manifest.get('limits'):
        reasons.append('limits in force differ from the frozen manifest: no deadline or budget change is admitted')
    _check_health(infra_health, sha, reasons)

    limits = manifest.get('limits', {})
    timing = manifest.get('timing_basis', {})
    for term in manifest_mod.TIMING_TERMS:
        if term not in timing:
            reasons.append('timing basis absent for ' + term)
    derived = search.derive(state)
    search_view = dict(status=derived['status'], detail=derived['detail'], candidate=derived['candidate'],
                       bracket=derived['bracket'], counts=derived['counts'], result=derived['result'],
                       condition_id=state.condition_id, trials_recorded=state.trial_ids())
    if reasons:
        return Admission(REJECTED, reasons, evaluated_at.isoformat(), sha, {}, {}, search_view, None)

    cost = estimate_cost(manifest)
    if cost['session_estimate_usd'] > limits['max_estimated_session_usd']:
        reasons.append('session estimate %.6f USD exceeds max_estimated_session_usd %.6f'
                       % (cost['session_estimate_usd'], limits['max_estimated_session_usd']))
    if cost['estimated_outbound_gib'] > limits['max_estimated_transfer_gib']:
        reasons.append('estimated outbound %.6f GiB exceeds max_estimated_transfer_gib %.6f'
                       % (cost['estimated_outbound_gib'], limits['max_estimated_transfer_gib']))

    if derived['next'] is None:
        time_view = dict(note='no legal remaining workload; collect, export and delete under the cap')
        decision = REJECTED if reasons else NO_REMAINING_WORK
        if not reasons:
            reasons = [derived['status'] + ': ' + derived['detail']]
        return Admission(decision, reasons, evaluated_at.isoformat(), sha, time_view, cost, search_view, None)

    cap_s = limits['max_session_duration_s']
    reserve_s = limits['teardown_reserve_s']
    grace_s = limits['evidence_recovery_grace_s']
    workload_deadline_c_s = cap_s - reserve_s
    if phase not in ('pre_create', 'provisioning', 'pair_ready'):
        raise ValueError('unknown phase ' + repr(phase))
    if phase == 'pre_create' and t0 is not None:
        reasons.append('pre_create admission cannot ignore a recorded t0')
        return Admission(REJECTED, reasons, evaluated_at.isoformat(), sha, {}, cost, search_view, None)
    elapsed_s = 0.0
    if phase != 'pre_create':
        if t0 is None:
            reasons.append(phase + ' admission requires the recorded t0')
            return Admission(REJECTED, reasons, evaluated_at.isoformat(), sha, {}, cost, search_view, None)
        elapsed_s = (evaluated_at - parse_utc(t0)).total_seconds()
        if elapsed_s < 0:
            reasons.append('clock reports now before t0; refusing to admit on an inconsistent clock')
    pre_workload = {}
    if phase != 'pair_ready':
        pre_workload = dict(create_bootstrap_s=timing['create_bootstrap_s']['seconds'],
                            readiness_access_s=timing['readiness_access_s']['seconds'])

    paths = search.legal_paths(state)
    costed = [path_cost(manifest, p) for p in paths]
    maximal = max(costed, key=lambda c: c['total_s'])
    next_only = path_cost(manifest, [derived['next']])
    tail = dict(collection_export_s=timing['collection_export_s']['seconds'], evidence_recovery_grace_s=grace_s)
    required_s = elapsed_s + sum(pre_workload.values()) + maximal['total_s'] + sum(tail.values())
    next_only_required_s = elapsed_s + sum(pre_workload.values()) + next_only['total_s'] + sum(tail.values())
    slack_s = workload_deadline_c_s - required_s
    time_view = dict(
        phase=phase, t0=t0, elapsed_s=elapsed_s, pre_workload_terms=pre_workload,
        legal_remaining_paths=len(paths),
        maximal_path=dict(total_s=maximal['total_s'], count=maximal['count'],
                          scored_hold_s=maximal['scored_hold_s'], run_ids=maximal['run_ids'],
                          trials=maximal['trials']),
        tail_terms=tail, max_session_duration_s=cap_s, teardown_reserve_s=reserve_s,
        workload_deadline_c_s=workload_deadline_c_s, required_before_c_s=required_s, slack_s=slack_s,
        next_trial_only_required_s=next_only_required_s,
        next_trial_only_fits=next_only_required_s <= workload_deadline_c_s,
        timing_basis={k: dict(v) for k, v in timing.items()},
        formula='elapsed + pre_workload + max_over_legal_paths(sum(readiness_bound(N) + warmup + hold + '
                'reset + finalization + per_trial_export)) + collection_export + recovery_grace <= cap - reserve')
    if slack_s < 0:
        reasons.append('maximal legal remaining path needs %.1f s before C=%.1f s; short by %.1f s. '
                       'No deadline extension: freeze a smaller explicitly authorized scope or stop with a '
                       'labelled partial search.' % (required_s, workload_deadline_c_s, -slack_s))
    if resume_requested and derived['counts']['total'] and any(r.outcome is None for r in state.records):
        reasons.append('resume requested while a dispatched trial has no recorded outcome; it is incomplete, '
                       'not resumable')
    if reasons:
        return Admission(REJECTED, reasons, evaluated_at.isoformat(), sha, time_view, cost, search_view, None)
    next_run = dict(derived['next'].to_dict(), estimate=next_only['trials'][0], selection_detail=derived['detail'])
    return Admission(ADMITTED, ['legal remaining paths fit before C with %.1f s slack; estimate %.6f USD within limit'
                                % (slack_s, cost['session_estimate_usd'])],
                     evaluated_at.isoformat(), sha, time_view, cost, search_view, next_run)
