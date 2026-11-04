"""How many sessions the watchdog can promise a first Droplet delete by C, checked before any create.

Every armed session reserves one provider-request slot from ``C - lead`` until ``C + tail``. That covers
its one in-flight ownership read, then its first delete issued by C and held until that request's bound.
Ordinary work never uses reserved slots, so if at most ``slots`` reservations overlap at any instant,
each session's next deadline request has a free slot the moment it is due, whatever is hung elsewhere.

The check is deliberately conservative and is explicit: ``arm_session`` refuses a session that would
exceed it, before t0 exists, and says when arming again would fit. Nothing is ever created for it.
"""


def reservation(cleanup_c, lead_s, tail_s):
    return cleanup_c - lead_s, cleanup_c + tail_s


def overlap_peak(cleanup_c, others, lead_s, tail_s):
    """Most reservations held at once during this one's interval, itself included."""
    start, end = reservation(cleanup_c, lead_s, tail_s)
    overlapping = [span for span in (reservation(c, lead_s, tail_s) for c in others) if span[0] < end and span[1] > start]
    points = [start] + [span[0] for span in overlapping if span[0] > start]
    return max(1 + sum(1 for span in overlapping if span[0] <= point < span[1]) for point in points)


def overlapping(cleanup_c, others, lead_s, tail_s):
    start, end = reservation(cleanup_c, lead_s, tail_s)
    return [name for name, c in others.items()
            if reservation(c, lead_s, tail_s)[0] < end and reservation(c, lead_s, tail_s)[1] > start]


def wait_until_fits(cleanup_c, others, slots, lead_s, tail_s):
    """Seconds until arming would fit, as arming later moves C later. None if no slot is ever reserved."""
    if slots < 1:
        return None
    if overlap_peak(cleanup_c, others, lead_s, tail_s) <= slots:
        return 0.0
    candidates = sorted({c + tail_s + lead_s - cleanup_c for c in others})
    return next(delay for delay in candidates if delay > 0
                and overlap_peak(cleanup_c + delay, others, lead_s, tail_s) <= slots)


def overall_peak(cleanups, lead_s, tail_s):
    cleanups = list(cleanups)
    return max((overlap_peak(c, cleanups[:i] + cleanups[i + 1:], lead_s, tail_s) for i, c in enumerate(cleanups)), default=0)
