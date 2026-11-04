"""Time source for the registry and watchdog: persisted UTC deadlines, local monotonic waits.

The registry never trusts a controller's clock and never lets a clock change move a deadline
later. ``advance`` turns the wall clock, the boot-scoped monotonic clock and the persisted anchor
into one *effective* time that only ever moves forward:

  * wall clock stepped back:    the monotonic estimate keeps time, so C/D still arrive on time;
  * wall clock stepped forward: effective time follows it (cleanup may start early, never late)
    and the ratchet keeps it there, so correcting the clock cannot revive an expired session;
  * reboot or new process:      the persisted anchor is a floor; a behind RTC cannot rewind time.

A wall clock that disagrees with the estimate is reported as an anomaly. The registry turns that
into a durable incident and an unhealthy status, so new sessions are refused until it clears.
"""
import dataclasses
import datetime
import pathlib
import time

DEFAULT_TOLERANCE_S = 5.0
BOOT_ID_PATH = pathlib.Path('/proc/sys/kernel/random/boot_id')
UNKNOWN_BOOT = 'unknown-boot'


def iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()


def parse(text):
    stamp = datetime.datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp must carry a UTC offset: ' + str(text))
    return stamp.timestamp()


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


@dataclasses.dataclass
class Anchor:
    boot_id: str
    mono: float
    effective: float


def advance(anchor, wall, mono, boot_id, tolerance_s=DEFAULT_TOLERANCE_S):
    """Return ``(effective, new_anchor, anomaly)``; ``anomaly`` is None when the clocks agree."""
    if anchor is None:
        return wall, Anchor(boot_id, mono, wall), None
    # An unidentifiable boot cannot prove the two monotonic readings share an origin.
    same_boot = anchor.boot_id == boot_id and boot_id != UNKNOWN_BOOT and mono >= anchor.mono
    estimate = anchor.effective + (mono - anchor.mono) if same_boot else anchor.effective
    effective = max(wall, estimate)
    anomaly = None
    drift = wall - estimate
    if drift < -tolerance_s:
        anomaly = dict(kind='wall_behind_effective', wall=iso(wall), effective=iso(effective),
                       drift_s=round(drift, 3), same_boot=same_boot)
    elif same_boot and drift > tolerance_s:
        anomaly = dict(kind='wall_jumped_forward', wall=iso(wall), effective=iso(effective),
                       drift_s=round(drift, 3), same_boot=same_boot)
    return effective, Anchor(boot_id, mono, effective), anomaly
