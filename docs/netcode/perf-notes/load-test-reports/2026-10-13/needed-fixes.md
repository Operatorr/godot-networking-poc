# Needed fixes discovered while measuring the CAX11 baseline

These are findings for separate work. This campaign changes measurement collection and
the matrix's approved Snapshot/AoI comparison configs; it does not optimize gameplay,
the generator, protocol, or replication.

## Scheduler queue-age diagnostic does not measure deferred waiting

`sched_max_queue_age_ticks` takes the maximum `ticks_since_last_sent` across **all**
candidates, including immediately admitted ones. New entities use the current global
Tick count as their age. In `instrumented-50-preflight`, deferrals and budget saturation
were both zero, but the reported age reached 5172 Ticks and grew with process uptime.
This cannot establish a growing replication backlog.

The measurement build adds a separate observer of first deferral through admission or
AoI removal. It preserves scheduler selection, priority and wire diagnostics. A future
diagnostic correction should distinguish last-send age, new entities and actual deferred
wait; changing priority rules would be separate gameplay/replication work.

Source: `rust/server/src/net/broadcast.rs` (`schedule`, `create_delta_packet`).
Evidence: [short preflight observations](instrumented-50-preflight/steady.json).

## Legacy economics and Tick-rate report fields remain diagnostic

The bot's lifetime bandwidth combines upload/download application payloads and includes
the join ramp. Its Tick-rate estimator divides a lifetime observed Tick span by Phase-2
duration. The wire byte totals wrap at 2^32. These fields remain preserved in original
reports and excluded from steady-window economics and sustainability gates, as required
by the agreed matrix. Correcting them is separate harness/protocol work.
