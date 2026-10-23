# Idle150 native diagnostic — round 5

**One completed attempt; generator-invalid; 34/36 original matrix gates pass.** The only failures are per-identity offered cadence (48/150 peers) and mapped wire cadence (150/150 on both captures). No clean-cell or capacity certificate follows, and no ladder cell advances. The [machine summary](clean-idle150-audit-r5-20261023-summary.json) retains every original gate, per-peer rate/error/native count, exact period measurement and audit. The parent owns [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), campaign ledgers, plan and closure. There was no retry or other workload.

## Frozen identities and condition

Rust source **a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf**. Controller/helper commit **aac023031f4f24319447587985b389a85302ed08**; executed controller SHA-256 **1ae6c5aecf97bd1ad1993503830ed6ac8822833d1deae030863914378b6d1d37**. All 111 frozen helper identities still match. The ordinary candidate **fea24dd1ec75eb3a5e832e408489943ced88814f** remains unchanged.

```text
game de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot  56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Build mode is **verified-existing-build-copy**. R3 compiled both locked packages natively **on bots only**; R5 performed zero package compilations. Each host has a fresh, clean Rust-only cone checkout selected before checkout, every materialized blob and all Cargo files verified at the exact revision (62 Rust files plus 14 root files), and independent real, one-link ELF64/AArch64 executable copies with matching hashes and dependencies. R3 native origin, its object manifest, and reuse proof remain retained; no R5 native package compilation on either host is claimed.

Idle150 uses 30 Hz requested input, 100 ms stagger, seed 30, difficulty 1, 60 s warmup and a full 300 s measurement. Config SHA **0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370**. Game buffers are 2 MiB requested / 4 MiB effective receive/send; bot buffers remain native 212,992 B. OMEGA_NATIVE_DIAG=v1 is explicit. Native unimpaired network, no emission audit/perf or redundant inputs; no game/protocol/sim/input scheduler/throttle/channel/reliability/budget change.

## Workload and all original gates

Offered input is **29.688748361855–29.708747518717 Hz**, with **48** peers below 29.7 Hz. Wire is **26.476666666667–29.640000000000 Hz** on each capture, with **all 150** below 29.7 Hz. The offered interval is 300.012647601 monotonic seconds between the unchanged start/end rows; wire uses the scheduled 300-second UTC interval. Native adaptive shedding does not turn either failed gate into a pass. The offered deficit's cause and total causal observer overhead are not established.

All other 34 matrix gates pass. Full/steady bot Baseline-reference, unknown-entity, decode, send and panic counts are **zero**; full/steady game decode/send, UDP error and socket-error counters are **zero**. All **32,579,659** received-AoI positional records are matched: zero unknowns, actual >1150-unit observations or empty-evidence peers. The complete received stream retains the check before stale application discard; observed stale-discard counts are zero. Final report/recorder Snapshot counts reconcile through drain. There is no emission-audit substitution.

The steady window has **9,000 Ticks / 300 s = 30 Hz**. Tick work p99 is **10.140579 ms**, maximum **21.151211 ms**, with zero work samples above 33.333 ms. Snapshot age p99/max are **39.720696/68.912184 ms**; ActionConfirm age p99/max **67.657053/148.595138 ms**. The existing delivery and backlog predicates pass: deferred wait peaks at six Ticks; mean pending replication in first/last 30 s is **0/2.718888889**, with complete trajectories and gate definitions retained in JSON. These delivery observations do not count exact application-delivered inputs.

Journal export scans and retains all **456 records / 748,051 B**. Full/steady oversized, panic and suppression findings are zero. The quiet steady journal has no rows, but the requested period has complete independent observation coverage; it is not an unobserved interval being relabelled zero. The c4517a4 coverage prerequisite and all 36 original gate names and thresholds remain unchanged.

Legacy criteria are separate failures: **6.91 KiB/s** against strict <5 KiB/s, and **29.99996923560801 Hz** against raw-float >=30. The latter is **1,657,759 × 1000 / 55,258,690**, with 1 ms timestamp resolution. Its display-rounded 30.0 does not pass the exact comparison. The natural process exit 1 is retained; no code panic or watchdog abort reason is observed.

## Native closed lifetime, windows and ambiguity

All **150** peers have separate start, end and post-force_close **drained** rows, ending Closed. The end row retains **150 pending** inputs; drained retains **zero**. Closed counts reconcile per peer: **1,644,645 created = admitted = retired**, comprising **1,619,035 full input Socket handoffs + 25,610 no-attempt retirements**. All input attempts return full length. All-datagram attempts/handoffs are **3,167,276** each. Zero/partial/error returns and all observer limit/parser/write/untracked/duplicate/unmatched/receive/service error counters are zero. Trace length, ordinal, timestamp, endpoint prefix and final error/count checks pass independently; raw trace is **105,257,280 B**.

Independent classification requires equal pre/post throttle, one +7 counter step and the skip predicate. **25,187** no-attempt retirements have that stable witness. **273** have changed throttle and **150** have no single-step predicate witness; all **423 remain ambiguous**. The raw native pre-only witness counter is 25,460, not 25,460 stable proofs. The extra 150 no-witness retirements occur between end and drained, matching the end's pending count; they are not silently attributed to throttling. Minimum observed throttle is **10/32**. The analyzer's strict evidence-complete flag remains **false** because of these ambiguities, while closed lifetime accounting passes. This is evidence for specified shedding in the witnessed subset, without full causal attribution or historical magnitude claims.

In the requested UTC window, **1,336,571 admissions − 1,311,151 handoffs = 25,390 no-attempt admissions + 39 carried out − 9 carried in**. Every peer independently balances. Trace-bracket pending estimates at the planned boundaries are 9/149; recorder endpoint counts are 11/150 at their actual timestamps. Bot start/end lateness is **0.204943/12.852544 ms**. These are different endpoints; offered-boundary counts are not substituted for native UTC-window counts.

Lifetime input-command captures equal the native handoff count **1,619,035 on each host**, including per-peer equality. Bot capture also equals all 150 per-peer native window counts, total **1,311,151**. Game capture totals **1,311,153** in that clock window: 146 peers equal, one is one below native, and three are one above. Exact per-peer counts, timestamps and boundary candidates are retained; the command identities and cause of those four per-peer differences remain unresolved. This is not a game-loss count. The 299 complete integer-second descriptive bins are separately labelled in JSON and do not replace the requested 300-second gate.

All **25,175 sampled 1-in-64 input fingerprints** match both complete captures. Sampling cannot prove all-datagram identity, no drops, or application delivery. Retirement timestamps are post-service record writes, not exact Drop instants. Native outgoing/reliable queues and std UDP receive truncation remain unavailable, not zero. Measured observer sections total **70,153,372,362 ns**; this is not total causal overhead, and the laptop parser timing probe is not remote cadence-fix evidence. **Application delivery and historical cause remain UNKNOWN.**

## Controller and preservation validation

The repaired monitor publishes both schedules, then requeries both hosts before further decisions. Actual remaining warmup lead is **38.836221416 s**, above the unchanged ten-second requirement. Fresh post-publication game/bot samples are **0.824318589/1.218813589 s** old; the cached-status abort does not recur. Natural termination is accepted: the final poll has no bot process identity and has the required guard, with no controller abort. No missing-guard grace interval was observed remotely; bounded-grace regressions remain the proof of that edge. End/drained separation is now validated remotely.

Before any source/binary staging: **8,987,701,248 B free**, **160,548,054 B allowance**, leaving **237,218,602 B** above the unchanged 8 GiB guard. Before workload staging: **8,968,957,952 B free**, **144,424,960 B allowance**, **234,598,400 B remaining**. Same-device/realpath/device/inode/hash/owner/mode proof precedes both stages. Stopped original measurement is hashed and atomically renamed without copy fallback; both audits prove original inodes/hash prefixes and recreated destination uid/gid/mode. Zero additional original-payload allowance depends on that proof.

The game-host allowances remain 16 MiB live game payload, 24 MiB journal, 42 MiB role-only archive, 32 MiB margin, plus exact source/bundle/object/binary/original-executable/config/manifest/directory costs. The measured game archive is **3,206,673 B**; bot archive is **64,959,373 B** on the separately measured bot host. Ordinary 1 GiB and R1/R2/R3 caps remain unchanged. No cleanup, package change, purchase/resize or evidence/source/journal/binary/archive deletion occurred.

**Automatic restoration passed without manual intervention.** Two fresh independent audits, **r5-release-a** and **r5-release-b**, pass **103 and 103 bounded commands respectively** (90 s per command). They verify every prior binary/archive/closed state, all candidates and sparse blobs (R2/R3/R4/R5), all 116 game + 19 bot prior-original files, frozen recovery scripts/manifests/markers, new atomic rename and native paths/ownership/mode, ordinary **524,288 B game buffers**, maintenance, qdisc/empty filters/firewall, zero players, quiet queues and no active owned/competing workload units/processes. Final free storage is game **8,937,119,744 B**, bots **18,251,624,448 B**. **Both hosts released.**

Fresh local census covers **6,234** pre-existing files with zero changed/missing files. The two parent ledger updates relative to R4's 6,070-file baseline are explicitly a new baseline; equality to their older bytes is not claimed. R1–R4 reservations, reports, binaries, archives, original backups and evidence remain sealed. New workload and private bundles have verified member hashes and fresh real extraction, with no symlinks/hardlinks. All **72 selected Python checks** pass, including failing-before/passing-after exact R5 support, retained-delay monitor tests, actual native binaries, real-copy/sparse and preservation probes. Rust source is unchanged; retained parent checks are 240 passes, three ignored probes, Clippy green with two old warnings, formatting and extension green. No expensive Rust repeat was run.

Workload archive SHA-256 values match remote/local and extracted member proof:

```text
game.tar.gz 4937100dd34e90ebb56f679711173f039ee58ded458e96a5abd3001a06fde606
bots.tar.gz b8b32aada6645a3ecbecc1dc0c8ff0256b5a621d391419674a0f6fbaa0dbb33d
```

R2's 21,991 stable/222 changed-throttle witnesses and 11 full/7 steady game-count shortfall remain sealed and qualified. R3's 83 stable witnesses, killed suffix and one-command descriptive-prefix difference remain unchanged; R4 remains zero-launch/resource-blocked with all gates null. R5 neither upgrades their missing evidence nor attributes historical cause. **Stop after this one attempt.** Parent follow-up retains the two failed cadence gates, ambiguous retirements, clock-window differences and unknown causal overhead/application delivery. No PR, push, issue/map/plan/parent-ledger edit or additional experiment.
