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


def session_manifest(session_id='do-cap-1v1g-20261030a', cap_s=3600, reserve_s=120, grace_s=300):
    """A frozen capacity manifest for any session id and deadline, as the planner would emit it."""
    import manifest as manifest_mod
    frozen_conditions = conditions()
    session = frozen_conditions['session']
    session['id'] = session_id
    session['ownership_tags'] = dict(session='omega-session:' + session_id, game='omega-role:game:' + session_id,
                                     bot='omega-role:bot:' + session_id)
    frozen_conditions['evidence']['local_root'] = 'loadtest-runs/digitalocean/' + session_id
    frozen_conditions['limits'].update(max_session_duration_s=cap_s, teardown_reserve_s=reserve_s,
                                       evidence_recovery_grace_s=grace_s)
    return manifest_mod.freeze_manifest(frozen_conditions, preflight(), FROZEN_AT)


class ScriptedClock:
    """Independent wall and boot-scoped monotonic clocks, moved only by the fixture."""

    def __init__(self, wall=T0_WALL, mono=1000.0, boot='boot-a'):
        self.wall_value, self.mono_value, self.boot = wall, mono, boot

    def wall(self):
        return self.wall_value

    def mono(self):
        return self.mono_value

    def boot_id(self):
        return self.boot

    def advance(self, seconds):
        self.wall_value += seconds
        self.mono_value += seconds

    def jump_wall(self, seconds):
        self.wall_value += seconds

    def reboot(self, downtime_s=0.0, boot='boot-b', rtc_error_s=0.0):
        self.wall_value += downtime_s + rtc_error_s
        self.mono_value = 5.0
        self.boot = boot


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
