"""Shared loaders for the offline fixtures; copies are deep so tests can mutate freely."""
import copy
import json
import pathlib

FIXTURES = pathlib.Path(__file__).with_name('fixtures')
FROZEN_AT = '2026-10-30T12:00:00+00:00'


def load(name):
    return json.loads((FIXTURES / name).read_text())


def conditions():
    return copy.deepcopy(load('conditions_capacity_1vcpu_1g.json'))


def preflight():
    return copy.deepcopy(load('preflight_sgp1_fake.json'))


def health(sha):
    return dict(registry=dict(healthy=True, acknowledged_manifest_sha256=sha),
                watchdog=dict(healthy=True, identity='omega-watchdog@mgmt-1', acknowledged_manifest_sha256=sha))


T0_WALL = 1793361600.0                  # 2026-10-30T12:00:00+00:00 expressed as epoch seconds
REGISTRY_ID = 'omega-registry-mgmt-1'
WATCHDOG_IDENTITY = 'omega-watchdog@mgmt-1'


def session_manifest(session_id='do-cap-1v1g-20261030a', cap_s=3600, reserve_s=120, grace_s=300, retained=(), telemetry_schema=None):
    """A frozen capacity manifest for any session id and deadline, as the planner would emit it. Its telemetry schema is a placeholder the real prover refuses, unless one is given."""
    import manifest as manifest_mod
    frozen_conditions = conditions()
    if telemetry_schema is not None:
        frozen_conditions['telemetry_schema'] = telemetry_schema
    session = frozen_conditions['session']
    session['id'] = session_id
    session['retained_resources'] = list(session['retained_resources']) + list(retained)
    session['ownership_tags'] = dict(session='omega-session:' + session_id, game='omega-role:game:' + session_id,
                                     bot='omega-role:bot:' + session_id)
    frozen_conditions['evidence']['local_root'] = 'loadtest-runs/digitalocean/' + session_id
    frozen_conditions['limits'].update(max_session_duration_s=cap_s, teardown_reserve_s=reserve_s,
                                       evidence_recovery_grace_s=grace_s)
    return manifest_mod.freeze_manifest(frozen_conditions, preflight(), FROZEN_AT)


class ScriptedClock:
    """Independent wall and boot-scoped monotonic clocks, moved only by the fixture."""

    def __init__(self, wall=T0_WALL, mono=1000.0, boot='boot-a', synced=True):
        self.wall_value, self.mono_value, self.boot, self.synced = wall, mono, boot, synced

    def wall(self):
        return self.wall_value

    def mono(self):
        return self.mono_value

    def boot_id(self):
        return self.boot

    def utc_verified(self):
        return self.synced

    def advance(self, seconds):
        self.wall_value += seconds
        self.mono_value += seconds

    def jump_wall(self, seconds):
        self.wall_value += seconds

    def reboot(self, downtime_s=0.0, boot='boot-b', rtc_error_s=0.0, synced=None):
        """A wrong RTC comes up unsynchronized unless the fixture says otherwise."""
        self.wall_value += downtime_s + rtc_error_s
        self.mono_value = 5.0
        self.boot = boot
        self.synced = rtc_error_s == 0.0 if synced is None else synced

    def time_sync(self, correction_s):
        """The time daemon steps the wall clock to true time and reports it synchronized."""
        self.wall_value += correction_s
        self.synced = True


class TimedExecutor:
    """Every provider request is issued at once and answered ``latency_s`` of scripted time later."""

    def __init__(self, latency_s=34.0):
        self.latency_s = latency_s
        self.clock = None
        self.pending = []

    def submit(self, call, done, session_id=None):
        import watchdog
        self.pending.append((self.clock.mono() + self.latency_s, watchdog._invoke(call), done))

    def release_due(self):
        due = [entry for entry in self.pending if entry[0] <= self.clock.mono()]
        self.pending = [entry for entry in self.pending if entry[0] > self.clock.mono()]
        for _, result, done in due:
            done(*result)

    def run(self, stack, seconds):
        for _ in range(int(seconds)):
            stack.clock.advance(1)
            self.release_due()
            stack.watchdog.tick()


class DeferredExecutor:
    """Hold each provider call until the fixture releases it: slow requests without sleeping."""

    def __init__(self, hold_sessions=None):
        self.pending = []
        self.hold_sessions = hold_sessions      # None holds every session; otherwise only these

    def submit(self, call, done, session_id=None):
        if self.hold_sessions is None or session_id in self.hold_sessions:
            self.pending.append((call, done))
        else:
            import watchdog
            done(*watchdog._invoke(call))

    def release(self, count=None):
        import watchdog
        count = len(self.pending) if count is None else count
        batch, self.pending = self.pending[:count], self.pending[count:]
        for call, done in batch:
            done(*watchdog._invoke(call))
        return len(batch)
