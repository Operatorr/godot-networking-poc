# Instrumented control before a capacity change

With `OMEGA_MEASURE_DIR` unset, the new socket counters and loop timers remain
disabled. With it set, the existing one-second `server.ndjson` observations add:

- Cumulative receive-attempt gap histogram, count, sum and maximum. Gaps include
  time between nonblocking calls, including normal idle sleep. They measure read
  opportunities, **not** packet arrival time or queue residence time.
- Actual adapter receive calls, datagrams, empty reads and errors, plus send calls,
  zero-byte sends of nonempty buffers, and send errors. Zero-byte sends expose the
  pinned adapter's `WouldBlock` return independently of application enqueue success.
- Cumulative main-loop phase timing for ENet service plus application routing,
  `World::tick` (including replication), outbox encoding/enqueue, and ENet flush.
  Metrics emission outside the Tick is not included in the outbox phase timer.
- `timing_bounds_us` defines histogram upper bounds; the last bucket exceeds the
  final bound. Counts and sums can be differenced between samples. Maxima are
  cumulative and must not be subtracted or described as interval maxima.

Boundary rows have `transport: null`; ordinary one-second rows have the current
socket counters. This keeps the existing matched application counter boundaries
intact. Phase timings are elapsed wall time; they do not replace CPU profiles.
The receive observer uses one monotonic-clock read per adapter receive attempt.
Its causal overhead is unknown until matched measurements; record it as an
instrumented build, never as an optimized capacity build.

The same control uses bot ramp observations from `3b910cd`. Normal settings and
effective socket buffers remain unchanged. Its purpose is to align read gaps,
loop-phase work, socket overflow, actual per-bot input scheduling and delivery.
Wire cadence and reliable retries still require independent compact flow evidence.

The loopback socket regression verifies that enabled observation preserves payloads
and distinguishes successful datagrams from empty nonblocking reads. Workspace
checks and remote control validation are recorded in the iteration ledger.
