# Reliable event pressure before and after overflow

Existing application counters from the [bitmap comparison](bitmap-comparison.md)
show substantial reliable GameEvent fan-out before the first receive-buffer
error interval (16.327–17.327 s). This is an offline analysis of the same experiment,
not another run or a transport-policy change.

| Requested elapsed window | Actual sample span | GameEvent sends | Baseline sends | GameEvent application bytes | Baseline application bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5–15 s | 9.010530 s | 327,631 | 247 | 4,700,505 | 200,335 |
| 15–20 s | 4.009189 s | 453,894 | 105 | 5,866,205 | 117,195 |
| 20–25 s | 4.468950 s | 618,692 | 93 | 7,501,919 | 102,743 |

In the first window, PROJECTILE_FIRED accounts for 146,105 reliable application
sends, EXP_GAIN 64,981, and DAMAGE 48,142. Their source-event counts are 1,580, 672,
and 512 respectively: fan-out multiplies event production into per-peer sends.
Baselines alone therefore do not explain the volume of application-enqueued
reliable work before initial overflow.

These are successful application enqueue counts/encoded payload bytes from
`record_message`, not UDP packet counts, delivered events, retransmissions or
ACKs. ENet coalesces commands; a single baseline may fragment. The previous wire
and profile evidence separately measures ACK/retry pressure and reliable-command
removal CPU. This analysis does not prove a specific event causes overflow, or
justify changing event reliability/recipients without a semantics review.

[Exact counters and timestamp boundaries](reliable-event-pressure.json) retain
all nonzero event categories. Reproduction: read cumulative `server.ndjson`,
select samples whose `utc_ns` lies inside each requested interval relative to
`bots/workload-start.json`'s `utc_ns`, and subtract first from last. Sum
`event_sends`; use channel 1 of `sent_bytes_by_type_channel` types 67 (GameEvent)
and 65 (baseline Snapshot). The aggregate intervals exclude boundary fragments;
they must not be normalized to the nominal 10/5-second duration.
