# Sustained generator profile — predeclared diagnostic

Exactly one new workload on the shared CAX11 pair, after verified cleanup of
[Strategy 150](capacity150.md). This is a diagnostic repetition to locate its
newly demonstrated generator limit, not a capacity pass or a routine confirmation.
No game/bot rebuild, scheduling change, workload reduction, buffer change, logging
suppression or network tuning is part of this condition.

## Ranked explanations and predictions

1. **Projectile-owner history increases per-input scan cost.** The bot retains
   PROJECTILE_FIRED owners, clears visible entities on a baseline, and removes an
   owner only on a removal record. `scan_for_monster_hits` scans the owner map on
   each living input. If this dominates, late CPU samples should concentrate in
   that scan or its inlined instructions, more than during the early window.
   Actual retained owner-map size is not instrumented and remains unknown.
2. **Transport, decode and Strategy processing consume the CPU budget.** If these
   dominate instead, samples should concentrate in ENet, Snapshot decoding or
   behavior decisions, even without evidence for the owner scan. The old ramp
   profile already showed these costs; it does not quantify sustained behavior.
3. **Serial polling and scheduling produce missed input deadlines.** If long
   polling cycles explain the loss of cadence, per-second CPU/profile intervals
   and input-gap/missed-schedule counters should align. Existing observations do
   not directly time each polling cycle; no cycle duration is inferred as fact.

These hypotheses can coexist. Inlining or unresolved stacks may prevent a clean
distinction. Retain raw addresses and report that limitation instead of assigning
ambiguous `Bot::poll` samples to a specific source loop.

## Frozen condition

Use the exact existing game `f1cc5d6` (SHA-256
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`)
and control bot (SHA-256
`831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`).
Preserve the Strategy 150 command, seed 30, difficulty 1, Class rotation, 30 Hz
input/Tick/Snapshot, 100 ms stagger, original AoI/LOD/budgets and game effective
receive/send buffers 4,194,304 / 524,288 bytes. Bot buffers remain 212,992 each.
Use the same 60-second global warmup and 300-second window to compare the offered
cadence trajectory; score it only as diagnostic. World entropy differs between runs.

Use collector/counting source `994cce8` and the sustained capture wrapper unchanged
in semantics. Namespace `udp-generator-profile-20261021` must be new and once-only.
The new controller may correct byte-array journal extraction and add bounded perf
lifecycle management; preserve the historical executed capacity controller.

## One added observation: bounded generator CPU profiles

Only the bot process is profiled. Use the installed compatible perf and the prior
validated `cpu-clock` 99 Hz, DWARF 8192-byte stack, monotonic clock, 256 mmap pages,
no build-id-cache updates and no online debuginfod retrieval. Arm a local remote
supervisor before launch; attach to the verified bot PID after the actual Phase 2
marker. Record two separate windows: **Phase 2 +0 to +25 seconds** and
**Phase 2 +180 to +205 seconds**. Record actual start/stop offsets and any missed
early prefix; never backfill nominal coverage. A failed first recording does not
authorize another workload.

Each recording has a 25-second active limit, 30-second supervisor/unit lifetime,
30 MiB soft data limit and 32 MiB hard file limit; at most 50 active recording
seconds and 64 MiB perf data in total. Finalization consumes the lifetime margin.
No concurrent game profiler or kernel tracer. Disposable sampler preflight is
permitted without a game workload; no installation or policy change is needed.

Decode offline with bounded commands. Report actual/raw sample counts, effective
samples per CPU-second, lost/throttle records, unwind coverage, unknown symbols,
recorder/supervisor resources, clock anchors, and self/inclusive hot paths in both
windows. Source/disassembly attribution must identify its evidence and uncertainty.
Compare offered/wire cadence, missed schedules, population, game Tick/delivery,
socket errors, retry pressure and collector resources in profile-on and adjacent
profile-off intervals. Such comparisons cannot establish causal profiler overhead.

## Operational and evidence bounds

Keep the capacity controller's 180-second ramp, 550-second workload, 600-second
capture/host collection and 720-second restoration limits; 48 MiB capture, 64 MiB
files and 512 MiB collection cgroups. Stop on join failure, population collapse,
runtime-identity change, stale observations, or a resource guard. Do not relax
gates or extend a run to obtain a preferred result.

Publish measurement schedules atomically only after the real Phase 2 marker.
Verify PID/invocation/executable hash and buffers immediately before the swarm and
throughout. Keep complete counts plus bounded log excerpts; mark incomplete raw
retention explicitly. Preserve original measurement files before service restart.
Archive/checksum evidence, restore original service/config/network/maintenance,
verify zero players and no owned bots/collectors/profilers/timers, and independently
audit cleanup before returning to the parent. Leave remote evidence intact.

Deliver a compact report and summary, with repeated raw rows private. Historical
Strategy 100 remains the highest validated population until a later valid capacity
cell passes all gates. Choose a code intervention only after this diagnostic result.
