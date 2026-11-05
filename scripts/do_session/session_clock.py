"""Time source for the registry and watchdog: persisted UTC deadlines, local monotonic waits.

The registry never trusts a controller's clock and never lets a clock change move a deadline
later. ``advance`` turns the wall clock, the boot-scoped monotonic clock and the persisted anchor
into one *effective* time that only ever moves forward:

  * wall clock stepped back:    the monotonic estimate keeps time, so C/D still arrive on time;
  * wall clock stepped forward: effective time follows it (cleanup may start early, never late)
    and the ratchet keeps it there, so correcting the clock cannot revive an expired session;
  * new process, same boot:     the monotonic estimate carries on across the restart;
  * reboot:                     the monotonic origin is gone, so downtime is unknowable from local
    state. Not going backward proves nothing: an RTC 300 s behind after 600 s of downtime still looks
    like 300 s of downtime. Only a clock the kernel reports as synchronized is trusted. Anything else
    is ``reboot_time_unverifiable``, and the registry fails closed on it.

A wall clock that disagrees with the estimate is reported as an anomaly. The registry turns that
into a durable incident and an unhealthy status, so new sessions are refused until it clears.
"""
import ctypes
import dataclasses
import datetime
import pathlib
import time

DEFAULT_TOLERANCE_S = 5.0
BOOT_ID_PATH = pathlib.Path('/proc/sys/kernel/random/boot_id')
UNKNOWN_BOOT = 'unknown-boot'
REBOOT_TIME_UNVERIFIABLE = 'reboot_time_unverifiable'
ADJTIMEX_TIME_ERROR = 5     # adjtimex(2): the kernel clock is not synchronized

# Timing policy shared by the planner, the registry and the watchdog.
PROVIDER_REQUEST_BOUND_S = 35.0     # how long this client waits for one provider request; not a provider guarantee
OWNERSHIP_PREPARE_LEAD_S = PROVIDER_REQUEST_BOUND_S + 5.0   # read-only: one ownership read, ticks and commits before C
DELETE_ISSUE_MARGIN_S = 0.5         # the deadline tick runs this long before C, so a delete is issued by C
DISPATCH_LAUNCH_WINDOW_S = 30.0     # how long a dispatch grant may wait before its launch
CREATE_START_WINDOW_S = 10.0        # a create grant unused for this long must not be sent


def iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()


def parse(text):
    stamp = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp must carry a UTC offset: ' + str(text))
    return stamp.timestamp()


def suspend_aware_monotonic():
    """Elapsed time that keeps counting while a laptop sleeps, which ``time.monotonic`` may not do."""
    for name in ('CLOCK_BOOTTIME', 'CLOCK_MONOTONIC'):
        if hasattr(time, name):
            return time.clock_gettime(getattr(time, name))
    return time.monotonic()


def controller_boot_id(libc=None):
    """This machine's boot, where it will say: Linux's ``boot_id``, or the boot session UUID macOS keeps. Otherwise ``UNKNOWN_BOOT``, and then no monotonic reading an earlier process took can be held to this one.

    For the controller only, which keeps a monotonic reading with a durable record for whichever process reads it next. The registry's clock keeps its own ``SystemClock.boot_id``.
    """
    try:
        text = BOOT_ID_PATH.read_text().strip()
        if text:
            return text
    except OSError:
        pass
    try:
        libc = libc or ctypes.CDLL(None)
        buffer, size = ctypes.create_string_buffer(64), ctypes.c_size_t(64)
        if libc.sysctlbyname(b'kern.bootsessionuuid', buffer, ctypes.byref(size), None, ctypes.c_size_t(0)) == 0 and buffer.value:
            return 'macos-' + buffer.value.decode('ascii', 'replace')
    except (OSError, AttributeError):
        pass
    return UNKNOWN_BOOT


def kernel_time_synced(libc=None):
    """True only when the kernel says a time-sync daemon disciplines the clock (adjtimex, read-only)."""
    try:
        libc = libc or ctypes.CDLL(None)
        timex = ctypes.create_string_buffer(512)    # zeroed struct timex; modes 0 changes nothing
        state = libc.adjtimex(timex)
    except (OSError, AttributeError):
        return False                                # no such call, so nothing is verified
    return 0 <= state < ADJTIMEX_TIME_ERROR


class SystemClock:
    """CLOCK_BOOTTIME counts suspended time; plain monotonic is only a development fallback."""

    def wall(self):
        return time.time()

    def mono(self):
        if hasattr(time, 'CLOCK_BOOTTIME'):
            return time.clock_gettime(time.CLOCK_BOOTTIME)
        return time.monotonic()

    def boot_id(self):
        try:
            return BOOT_ID_PATH.read_text().strip() or UNKNOWN_BOOT
        except OSError:
            return UNKNOWN_BOOT

    def utc_verified(self):
        return kernel_time_synced()


@dataclasses.dataclass
class Anchor:
    boot_id: str
    mono: float
    effective: float


def advance(anchor, wall, mono, boot_id, tolerance_s=DEFAULT_TOLERANCE_S, utc_verified=False):
    """Return ``(effective, new_anchor, anomaly)``; ``anomaly`` is None when the clocks agree."""
    if anchor is None:
        return wall, Anchor(boot_id, mono, wall), None
    # An unidentifiable boot cannot prove the two monotonic readings share an origin.
    boot_changed = anchor.boot_id != boot_id
    same_boot = not boot_changed and boot_id != UNKNOWN_BOOT and mono >= anchor.mono
    estimate = anchor.effective + (mono - anchor.mono) if same_boot else anchor.effective
    effective = max(wall, estimate)
    anomaly = None
    drift = wall - estimate
    if not same_boot and (drift < -tolerance_s or (boot_changed and not utc_verified)):
        anomaly = dict(kind=REBOOT_TIME_UNVERIFIABLE, wall=iso(wall), effective=iso(effective), drift_s=round(drift, 3),
                       same_boot=False, boot_changed=boot_changed, utc_verified=bool(utc_verified))
    elif drift < -tolerance_s:
        anomaly = dict(kind='wall_behind_effective', wall=iso(wall), effective=iso(effective),
                       drift_s=round(drift, 3), same_boot=same_boot)
    elif same_boot and drift > tolerance_s:
        anomaly = dict(kind='wall_jumped_forward', wall=iso(wall), effective=iso(effective),
                       drift_s=round(drift, 3), same_boot=same_boot)
    return effective, Anchor(boot_id, mono, effective), anomaly
