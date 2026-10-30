"""The accepted finite capacity search as a legal branch graph (issue #60 §2, #61 §1).

A search state is the ordered list of dispatched trials with their recorded outcomes. The
planner derives the ONE legal next trial from that history; it never offers a menu, retries,
extra seeds or a descending confirmation sweep. Legal remaining paths are enumerated by
branching PASS/FAIL from the current state until the search ends, so admission can bound
the maximum remaining time without summing incompatible branches.

Outcome vocabulary (scorer semantics, #60 §5):
  PASS   valid common-window pass
  FAIL   attributable game-host capacity failure with a valid generator
  INVALID_LOAD, INFRASTRUCTURE_FAILURE, INCONCLUSIVE   stop the batch; establish nothing
  INCOMPLETE   interrupted dispatched trial; its dependent branch becomes undecidable
"""
import dataclasses

COARSE_START = 25
COARSE_STEP = 25
COARSE_MAX = 500
REFINE_STEP = 5
REFINE_MAX_TRIALS = 4
CONFIRMATIONS = 3
EXPLORATION_HOLD_S = 60
CONFIRMATION_HOLD_S = 300
MAX_TRIALS_PER_CONDITION = 27
JOIN_STAGGER_S = 0.1          # global 100 ms join schedule
READINESS_FLOOR_S = 60
READINESS_MARGIN_S = 30
POST_AUTH_WARMUP_S = 2

PASS, FAIL = 'PASS', 'FAIL'
INVALID_LOAD, INFRASTRUCTURE_FAILURE, INCONCLUSIVE, INCOMPLETE = (
    'INVALID_LOAD', 'INFRASTRUCTURE_FAILURE', 'INCONCLUSIVE', 'INCOMPLETE')
OUTCOMES = (PASS, FAIL, INVALID_LOAD, INFRASTRUCTURE_FAILURE, INCONCLUSIVE, INCOMPLETE)
ADVANCING = (PASS, FAIL)
STOPPING = {INVALID_LOAD: 'stopped_invalid_load',
            INFRASTRUCTURE_FAILURE: 'stopped_infrastructure_failure',
            INCONCLUSIVE: 'stopped_inconclusive_evidence'}

COARSE, REFINE, CONFIRM = 'coarse', 'refine', 'confirm'


def nominal_ramp_s(target):
    return target * JOIN_STAGGER_S


def readiness_bound_s(target):
    """Accepted readiness bound; the nominal ramp already lives inside it (#60 §3)."""
    return max(READINESS_FLOOR_S, nominal_ramp_s(target) + READINESS_MARGIN_S)


@dataclasses.dataclass(frozen=True)
class Trial:
    run_id: str
    ordinal: int            # 1-based trial number within the condition (<= 27)
    phase: str              # coarse | refine | confirm
    target: int             # requested players N
    repetition: int         # 1 for exploration, 1..3 for confirmations
    hold_s: int
    predecessors: tuple     # run ids whose recorded evidence this trial's selection depends on

    def to_dict(self):
        return dict(dataclasses.asdict(self), predecessors=list(self.predecessors),
                    readiness_bound_s=readiness_bound_s(self.target),
                    nominal_ramp_s=nominal_ramp_s(self.target))


@dataclasses.dataclass(frozen=True)
class TrialRecord:
    trial: Trial
    outcome: str = None     # None while dispatched without a recorded outcome
    evidence_ref: str = None


@dataclasses.dataclass
class SearchState:
    condition_id: str
    records: list = dataclasses.field(default_factory=list)
    stop_reason: str = None  # external terminal stop: time/spend exhaustion, operator stop

    def with_record(self, record):
        return SearchState(self.condition_id, self.records + [record], self.stop_reason)

    def trial_ids(self):
        return [r.trial.run_id for r in self.records]


class SearchError(ValueError):
    pass


def run_id(condition_id, ordinal, phase, target, repetition):
    return '%s-t%02d-%s-n%03d-r%d' % (condition_id, ordinal, phase, target, repetition)


def _validate(state):
    seen = set()
    for index, record in enumerate(state.records):
        if record.trial.ordinal != index + 1:
            raise SearchError('trial ordinals must be contiguous from 1; found ' + record.trial.run_id)
        if record.trial.run_id in seen:
            raise SearchError('duplicate trial ' + record.trial.run_id)
        seen.add(record.trial.run_id)
        if record.outcome is not None and record.outcome not in OUTCOMES:
            raise SearchError('unknown outcome ' + repr(record.outcome))
        if record.trial.ordinal > MAX_TRIALS_PER_CONDITION:
            raise SearchError('trial ceiling exceeded')


def derive(state):
    """Replay the journal and return the search status plus the legal next trial (or None).

    Returns a dict with keys: status, result, candidate, bracket, counts, next (Trial|None),
    detail. ``status`` is 'in_progress' or a terminal label.
    """
    _validate(state)
    coarse = [r for r in state.records if r.trial.phase == COARSE]
    refine = [r for r in state.records if r.trial.phase == REFINE]
    confirm = [r for r in state.records if r.trial.phase == CONFIRM]
    counts = dict(coarse=len(coarse), refine=len(refine), confirm=len(confirm), total=len(state.records))
    base = dict(counts=counts, candidate=None, bracket=None, next=None, result=None)

    def terminal(status, detail, **extra):
        return dict(base, status=status, detail=detail, **extra)

    for record in state.records:
        if record.outcome in STOPPING:
            return terminal(STOPPING[record.outcome],
                            record.trial.run_id + ' recorded ' + record.outcome + ': remaining runs stop; '
                            'collect evidence and delete. No capacity is established.')
    if state.stop_reason:
        return terminal('partial_' + state.stop_reason,
                        'search stopped externally (' + state.stop_reason + '); partial evidence retained')

    passing = [r.trial.target for r in state.records if r.outcome == PASS and r.trial.phase != CONFIRM]
    candidate = max(passing) if passing else None
    base['candidate'] = candidate

    # ---- coarse phase -------------------------------------------------------------------
    failing_coarse = next((r for r in coarse if r.outcome == FAIL), None)
    last_pass_coarse = max([r.trial.target for r in coarse if r.outcome == PASS], default=0)
    if coarse and coarse[-1].outcome in (None, INCOMPLETE):
        return terminal('undecidable_incomplete_predecessor',
                        coarse[-1].trial.run_id + ' has no complete outcome; the next coarse branch is '
                        'undecidable. Do not infer PASS/FAIL or replay it inside this batch.')
    if failing_coarse is None:
        if last_pass_coarse < COARSE_MAX:
            target = last_pass_coarse + COARSE_STEP if coarse else COARSE_START
            ordinal = len(state.records) + 1
            predecessors = (coarse[-1].trial.run_id,) if coarse else ()
            trial = Trial(run_id(state.condition_id, ordinal, COARSE, target, 1), ordinal, COARSE,
                          target, 1, EXPLORATION_HOLD_S, predecessors)
            return dict(base, status='in_progress', next=trial,
                        detail='coarse ascent: ' + ('first rung' if not coarse else
                                                    'previous rung ' + str(last_pass_coarse) + ' passed'))
        bracket = dict(last_pass=COARSE_MAX, first_fail=None)
    else:
        bracket = dict(last_pass=last_pass_coarse, first_fail=failing_coarse.trial.target)
    base['bracket'] = bracket

    # ---- refinement phase ---------------------------------------------------------------
    if failing_coarse is not None:
        if refine and refine[-1].outcome in (None, INCOMPLETE):
            return terminal('undecidable_incomplete_predecessor',
                            refine[-1].trial.run_id + ' has no complete outcome; the refinement branch is '
                            'undecidable and the confirmation target cannot be chosen.')
        refine_failed = any(r.outcome == FAIL for r in refine)
        if not refine_failed and len(refine) < REFINE_MAX_TRIALS:
            target = bracket['last_pass'] + REFINE_STEP * (len(refine) + 1)
            ordinal = len(state.records) + 1
            last_pass_id = next((r.trial.run_id for r in reversed(state.records)
                                 if r.outcome == PASS and r.trial.phase != CONFIRM), None)
            predecessors = tuple(x for x in (failing_coarse.trial.run_id, last_pass_id) if x)
            trial = Trial(run_id(state.condition_id, ordinal, REFINE, target, 1), ordinal, REFINE,
                          target, 1, EXPLORATION_HOLD_S, predecessors)
            return dict(base, status='in_progress', next=trial,
                        detail='refinement inside bracket (%d, %d] at five-player resolution'
                               % (bracket['last_pass'], bracket['first_fail']))
        if candidate is None:
            return terminal('no_passing_target',
                            'even %d players failed: no passing target at the search resolution. This is '
                            'not proof that no smaller population could work.' % REFINE_STEP)

    # ---- confirmation phase -------------------------------------------------------------
    failed_confirmations = [r for r in confirm if r.outcome == FAIL]
    if failed_confirmations:
        return terminal('unconfirmed_variable',
                        'confirmation ' + failed_confirmations[0].trial.run_id + ' failed: candidate %d is '
                        'unconfirmed/variable. Bracket and every confirmation result are retained; no '
                        'replacement trial. Further attempts need a separately bounded batch.' % candidate,
                        result=dict(kind='unconfirmed_variable', candidate=candidate))
    passes = sum(1 for r in confirm if r.outcome == PASS)
    incomplete = [r for r in confirm if r.outcome in (None, INCOMPLETE)]
    if len(confirm) < CONFIRMATIONS:
        ordinal = len(state.records) + 1
        repetition = len(confirm) + 1
        establishing = [r.trial.run_id for r in state.records if r.trial.phase != CONFIRM
                        and r.trial.target == candidate and r.outcome == PASS]
        if failing_coarse is not None:
            establishing.append(failing_coarse.trial.run_id)
        first_refine_fail = next((r.trial.run_id for r in refine if r.outcome == FAIL), None)
        if first_refine_fail:
            establishing.append(first_refine_fail)
        trial = Trial(run_id(state.condition_id, ordinal, CONFIRM, candidate, repetition), ordinal, CONFIRM,
                      candidate, repetition, CONFIRMATION_HOLD_S, tuple(establishing))
        return dict(base, status='in_progress', next=trial,
                    detail='confirmation %d of %d at candidate %d (fresh 300 s run)'
                           % (repetition, CONFIRMATIONS, candidate))
    if incomplete:
        return terminal('unconfirmed_partial',
                        'confirmation set at %d is partial (%s incomplete): not a confirmed capacity. '
                        'Repeating needs a separately authorized batch.' % (candidate, incomplete[0].trial.run_id),
                        result=dict(kind='unconfirmed_partial', candidate=candidate, passes=passes))
    if passes == CONFIRMATIONS:
        if candidate == COARSE_MAX:
            return terminal('confirmed_search_cap_reached',
                            'three valid confirmations at %d: at least %d under this condition; search cap '
                            'reached, not a discovered ceiling.' % (COARSE_MAX, COARSE_MAX),
                            result=dict(kind='at_least', candidate=candidate, search_cap_reached=True))
        return terminal('confirmed',
                        'three valid confirmations at %d: observed confirmed candidate for this rented pair, '
                        'not provider-wide capacity.' % candidate,
                        result=dict(kind='confirmed', candidate=candidate, search_cap_reached=False))
    raise SearchError('unreachable confirmation state')   # pragma: no cover


def next_trial(state):
    return derive(state)['next']


def record_outcome(state, trial_id, outcome, evidence_ref=None):
    """Return a new state with the outcome recorded; outcomes are append-only and final."""
    if outcome not in OUTCOMES:
        raise SearchError('unknown outcome ' + repr(outcome))
    records = []
    found = False
    for record in state.records:
        if record.trial.run_id == trial_id:
            if record.outcome is not None:
                raise SearchError(trial_id + ' already has outcome ' + record.outcome + '; outcomes are final')
            record = TrialRecord(record.trial, outcome, evidence_ref)
            found = True
        records.append(record)
    if not found:
        raise SearchError(trial_id + ' was never selected in this batch')
    return SearchState(state.condition_id, records, state.stop_reason)


def dispatch(state, trial):
    """Return a new state with ``trial`` recorded as selected (outcome pending)."""
    expected = next_trial(state)
    if expected != trial:
        raise SearchError('trial ' + trial.run_id + ' is not the legal next trial')
    return state.with_record(TrialRecord(trial))


def legal_paths(state):
    """Enumerate every legal remaining path as a list of Trials, branching PASS/FAIL only.

    Stopping outcomes end a path immediately with no further trials, so they never make a
    path longer; the maximum over PASS/FAIL branches therefore bounds every legal remainder.
    """
    paths = []

    def walk(current, prefix):
        trial = next_trial(current)
        if trial is None:
            paths.append(list(prefix))
            return
        dispatched = current.with_record(TrialRecord(trial))
        for outcome in ADVANCING:
            walk(record_outcome(dispatched, trial.run_id, outcome), prefix + [trial])

    walk(state, [])
    return paths


def path_summary(path):
    holds = sum(t.hold_s for t in path)
    return dict(trials=len(path), scored_hold_s=holds, scored_hold_min=holds / 60.0,
                exploration=sum(1 for t in path if t.phase != CONFIRM),
                confirmations=sum(1 for t in path if t.phase == CONFIRM),
                run_ids=[t.run_id for t in path])


def campaign_trial_ceiling(condition_slugs, accepted_conditional=()):
    """Run-count ceiling across sessions: 27 per primary condition plus 27 per admitted conditional."""
    from manifest import GAME_CONDITIONS
    total = 0
    for slug in condition_slugs:
        info = GAME_CONDITIONS.get(slug)
        if info is None:
            raise SearchError('unknown condition ' + repr(slug))
        if info['kind'] == 'conditional' and slug not in accepted_conditional:
            raise SearchError('conditional condition ' + slug + ' is not explicitly admitted')
        total += MAX_TRIALS_PER_CONDITION
    return total
