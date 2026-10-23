# Idle 150 native transport diagnostic — blocked before launch

**Resource-blocked; zero remote workloads.** This is unfinished diagnostic work for [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), not a clean cell, capacity observation or historical causal attribution. The [machine summary](clean-idle150-audit-r1-20261022-summary.json) retains all identities, unknown counters, 36 unscored gates, audit checks and evidence hashes. The parent campaign remains on `fea24dd1ec75eb3a5e832e408489943ced88814f`; no ledger/plan/issue state was changed.

## Source, build and passive instrumentation

Instrumented bot source: **`ab535731b21860fcfdc3654288dd8821eaa63450`**. Both hosts natively built **both** packages with locked dependencies. Their exact source and top-level executable hashes agree:

```text
game  de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bots  a9325ad1bd90a24e3d1bdb08ce049fb5734d67471010af6f5425b104bda2f042
```

The game matches the required unchanged hash. Controller revision **`c4e0df946dae2a6729a920fab86c94e770c389d6`** only adds the opt-in dispatch/environment checks and stricter diagnostic resource stop; it does not change game/bot source after the instrumented commit. Exact executed controller SHA-256: `a887cc7bfb623ba9427e2af301a91d04778b7e8c3ee5d6c9ff2e5dd52b07cd1c`.

`OMEGA_NATIVE_DIAG=v1` forwards native Socket initialization, send and receive unchanged, including return values. It changes no buffers, packet modes/channels, input scheduling or throttle parameters. Default-off packets retain the ordinary allocation path and observation schema. Opt-in input-buffer retirement, native send attempts/full socket handoffs/zero/partial/error returns, service timing and numeric throttle/counter state are distinct observations. Native queue lengths remain unknown; packet-buffer lifetime measures only tracked input pending work. The unchanged std UDP implementation cannot detect receive truncation, which remains explicit. Public Debug is transiently parsed for a strict numeric whitelist; full Debug/address/auth strings are never emitted.

Traces are bounded to **16,384 × 64-byte records = 1 MiB per peer, 600 seconds**, with at most 64 tracked pending inputs per peer. Missing/changed numeric fields, parser/limit/write errors or unmatched accounting fail diagnostic evidence closed. A separate observer uses real application decoding; full-UDP fingerprints can independently reconcile its native handoffs against the retained v2 captures. Instrumentation adds overhead; measured observer sections are not a causal estimate of its total effect.

## Local evidence and validation

All **239 Rust workspace tests pass; 2 existing tests remain ignored**. Clippy passes with the two existing bot match warnings; formatting and client extension rebuild pass. **34 clean-run tests, 6 diagnostic dispatch/replay/resource/audit tests and 3 actual-ENet observer tests pass.** No game/protocol/simulation behavior changed.

The actual pinned ENet/real-codec lossless-link test observes **10,700 admissions → 10,700 native socket handoffs → 10,700 receiver deliveries** at stable delay. At variable delay it observes **10,700 → 10,699 → 10,699**, with exactly one no-attempt retirement matching the native single counter step and skip predicate; throttle minimum is 28/32. Pending inputs drain to zero; observer/transport errors are zero. Actual native UDP plus CLI opt-in smoke also validates three peers, 381 admissions, trace accounting and final drain. Its generic legacy harness exit is retained separately (0); it is not a remote capacity pass.

These tests establish observer behavior and a possible specified ENet mechanism. They do **not** identify the historical Idle150 deficit's cause or magnitude. The new remote adaptive-shedding, delayed-flush and collector-miscount hypotheses remain **unclassified**. No remote admission/socket/capture/delivery or throttle/timing/observer-cost counters were collected; all full/steady workload counters and legacy criteria are **unknown/not run**, not zero or passing. All 36 original gates remain enabled and unscored; no wire gate was weakened.

## Launch proof and storage blocker

Exactly **one exclusive local preflight reservation**, retained at `deployment/hetzner/results/clean-idle150-audit-r1-20261022/launch-reserved.json`; **zero workload launch attempts**. The controller stopped after two successful read-only hash queries with `game remote command timed out`. Its immediate connectivity cause is unknown. Later bounded ordinary and fresh non-multiplexed SSH checks both succeeded. No remote diagnostic namespace, manifest, invocation, runtime polls or workload archives exist; two independent audits prove namespace/process/unit absence. The reservation and failed preflight were preserved; no retry bypassed them.

At **2026-10-23 02:44:35 UTC**, game available space was **8,774,664,192 B**, only **184,729,600 B above the unchanged 8 GiB guard**. Its original measurement directory occupies **190,189,568 B** on ext4, with singly linked text files. The allocated preservation-copy budget alone exceeds that headroom by **5,459,968 B**, before original executable copies, diagnostic evidence, journal and archive. The diagnostic's stricter **96 MiB live game-evidence** stop, **24 MiB journal retention** and archive still need additional bounded headroom. The ordinary 1 GiB resource stop and all validity thresholds remain unchanged. No workload was launched under insufficient space.

Only the new proven diagnostic checkout's regenerable Cargo intermediates were reclaimed earlier: `deps`, `build`, `incremental`, `.fingerprint`, `examples`, allocated total **349,843,456 B**. Both exact source and game/bot hashes match before/after. Free space then rose **8,617,263,104 → 8,954,269,696 B**. Every top-level executable, original/frozen build, source tree, raw archive, historical analysis and closed state remains preserved. A fresh exact source/two-binary census of **all five clean game checkouts** finds **zero authorized reclaimable intermediates**. No further deletion or guard reduction is authorized. Additional game-host storage is the blocker.

The intended workload remains Idle150, 30 Hz, 100 ms stagger, seed 30, difficulty 1, 60 s warmup + 300 s measurement; config SHA `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`; game 2 MiB requested/4 MiB effective each; native bot buffers/network; no emission audit or profiler. None of that condition was claimed as remotely exercised.

## Idle preservation and private evidence

Automatic restoration was **not required or executed**: the workload controller never reached remote staging or service/config/unit/environment mutation. Two fresh exclusive **idle/preservation** audits, `blocked-final` and `blocked-recheck`, each pass **40/40 bounded commands (24 game + 16 bots), 90 s configured command timeout**, zero failed checks. They are not the unexecuted workload/restoration certificates.

Both prove original service/config/unit/executable and ordinary **524,288-byte receive/send buffers**, original measurement destination and every prior verified measurement backup, zero players, quiet queues, native qdisc/empty filters, unchanged firewall/maintenance, no owned/competing workload units/processes, all clean-source/top-level hashes and every prior binary/archive/closed-state hash. The prebuild census covers **21/16 executables and 85/86 archive/checksum files** on game/bots. Independent local preservation rechecks **5,206 historical files: zero changed or missing**. Final audit game available space is **8,773,840,896 B**. Both hosts remain released in original operating state.

Private bundles remain under ignored `deployment/hetzner/results`; no remote/local workload archives or evidence hashes are invented. Exact raw audit outputs, bounded command journals, test logs, native builds, source/bundle proof, local smoke traces, resource proofs and failed executed controller are retained. Bundle SHA-256 values:

```text
clean-idle150-audit-r1-20261022-preflight.tar.gz
  a4a75cebcde0549320630240f53098890684cba8992a2d07c2a5f9ed7ff3c346
clean-idle150-audit-r1-20261022-controller-blocked.tar.gz
  25684db3cbf4c81fe449504327cd1884def1d6c7c5a94fc10aadf78812f23519
clean-idle150-audit-r1-20261022-build.tar.gz
  8c51ba860d958afa84183af6ba9a5c26748ef7091c6e62a1dbbb1167c39aac28
```

The machine summary includes each audit output/command hash and both raw host-output hashes. Parent work remains storage recovery, a reviewed continuation respecting the retained reservation, the single matched diagnostic, future fixes/reruns, the held ladder and final assessment. Historical Idle150 cause and application input delivery remain **UNKNOWN**. No issue closure or deployment occurred.
