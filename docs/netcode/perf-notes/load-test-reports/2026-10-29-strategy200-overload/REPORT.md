# Strategy200 overload measurement — bounded inconclusive

The approved preparation **failed its local event-preservation prerequisite**.
The proposed 32-event bot scheduler drops queued reliable application events at
disconnect. It is not qualified for a remote Strategy200 observation. Preparation
stopped without a scheduler fix, overhead assessment, remote command or workload.
Server capacity and the historical disconnect cause remain unknown.

Owned by [Establish valid Strategy overload measurement without bot-host loss](https://github.com/Operatorr/godot-networking-poc/issues/46),
under the [author-approved bounded plan](https://github.com/Operatorr/godot-networking-poc/issues/46#issuecomment-6493273227).
The user approved that plan in the working session on 2026-10-29. Preparation
started at 09:42:39 UTC, with a 13:42:39 UTC deadline. The decisive local failure
was recorded before the 09:52:10 UTC stop audit. The 90-minute remote clock never
started; neither of the two remote attempt slots was consumed.

## Prerequisite and hypothesis

The minimum prerequisite is a complete original 300-second common window with
all 200 identities and original boundaries, every peer offering at least 29.7 Hz,
at least 29.7 Hz per mapped peer on both independent captures, zero bot-host
UDP/socket errors throughout the workload, complete counters and attribution,
clean full-window collectors, frozen identities, and qualified observer cost.
All 36 original acceptance predicates still apply independently. Missing data,
an aborted prefix or sampled socket zeros cannot satisfy this prerequisite.

The single approved hypothesis was that a fixed 32-event-per-poll budget would
remove bot-host receive loss at Strategy200 while preserving original offered
and wire cadence. Its local admission condition also required preserved event
order, eventual handling without discard, unbacklogged behavior and teardown
semantics. The scheduler failed that admission condition. The hypothesis was
**not tested on the remote host pair**, and is not reported as disproved there.

## What was executed

The isolated diagnostic is based on source
`a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf`. A generated reference and candidate
share a constructor seam for ENet's public Socket and virtual-time interfaces.
They execute actual Bot packet decoding/handling, Strategy decisions, shared
movement, input encoding and the unmodified pinned `rusty_enet =0.4.0`.
No network socket is opened by the synthetic replay.

The candidate changes only outer event-drain scheduling, with budget off or 32.
Ordinary runtime measurement and a compact whole-sweep observer were prepared;
native dependency observers, buffers, ENet behavior and the server were unchanged.
Harness-only traces witness actual received application events and encoded sends.
The [exact generated-source diff](experiment.patch),
[original-source provenance](source-provenance.json) and
[final experiment freeze](local-prerequisite-freeze.json) identify the code.

The final replay compared the constructor-adapted reference with candidate off,
candidate 32 and candidate 32 plus sweep observation. Stable, 512-event burst and
3,200-event sustained cases passed the disabled-reference, observer-parity and
event-order checks. The burst yielded a maximum 512 received events in one
reference poll versus 32 in the candidate; the sustained case yielded 65 versus
32. The stable case delivered 990 inputs across three peers, exercising repeated
u8 input-sequence wrap.

The decisive case delivered 512 reliable, uniquely numbered Game events to the
first peer just before teardown. At virtual **10,999 ms**, the reference handled
events 1–512; the candidate handled 1–32. At **11,000 ms**, both followed the
unchanged `begin_disconnect` path. The candidate's remaining **480** events were
discarded. The extra two virtual seconds of servicing did not recover them.
The final replay exited **101** on the received-event equality assertion.

Read-only, independent parsing of the retained event bytes verifies the exact
source id 999, Game-event type, target sequence and times. The reference has all
targets 1–512 in order; the candidate has exactly 1–32, with targets 33–512 missing.
See [raw replay output](parity-final.ndjson), [assertion stderr](parity-final.stderr)
and [independent assessment](independent-assessment.json).

This mechanism agrees with pinned ENet source: `enet_peer_disconnect` calls
`enet_peer_reset_queues`, which clears dispatched and incoming commands. The
existing full-drain loop processes the burst before disconnect; the proposed
budget leaves application events in those queues. This proves a problem in the
**new diagnostic scheduler condition**. It does not prove that the production
bot, game server or historical receive-loss episode has this defect.

## Earlier checks and qualifications

The [initial eight-case replay output](parity-initial.ndjson) also covered receive
error, unanswered authentication timeout, malformed packet and server teardown;
those initial cases passed. Its late burst arrived 20 ms before close, leaving
enough polls to empty the queue, so it did not validate pending-event teardown.
Those outputs are retained but do not qualify the final experiment.

An intermediate fixture placed the burst one virtual millisecond before close.
With the link's one-millisecond delivery delay, neither arm dispatched the burst
before disconnect. Its coverage assertion failed, rather than establishing a
scheduler difference; [output](parity-teardown.ndjson) and
[stderr](parity-teardown.stderr) remain retained. Correcting the fixture to two
milliseconds before close produced the decisive 512-versus-32 result. The
scheduler was not changed or optimized in response to either result. Earlier
output files are historical preparation logs; their earlier executable hashes
were not retained and are not represented by the final executable freeze.

One initial materialization failed because a protocol integration test imports a
frozen collector source outside `rust/`; the materializer was corrected to include
that source before the final experiment. An initial build command also targeted
the repository root instead of the generated workspace and did not compile code.
These setup errors consumed no remote attempt.

The production workspace's required command chain passed:
`cargo test --workspace && cargo clippy --workspace --all-targets && cargo fmt --check`.
Clippy retained two existing `collapsible_match` warnings in `load_test/src/bot.rs`.
Production source was not changed.

The generated standalone suite was **not fully green**: bot/unit, throttle and
native-wrapper tests passed, but the historical `native_terminal` integration
test failed because the new diagnostic CLI guard rejects its requested native
observer. The chained standalone Clippy/fmt/release-bot build therefore did not
run. The release replay executable did build, and generated-source formatting
ran before that build. No passing standalone workspace or ordinary diagnostic
bot executable is claimed. No test was skipped to promote the condition.

All **44 final frozen source/build files** retained their exact SHA-256 values
after the failed replay. [Post-stop immutability proof](post-stop-immutability.json)
checks every entry. [Evidence hashes](evidence-sha256.json) cover the retained raw
results, assessments and source diff. The freeze includes compiler/Cargo versions
and the local release replay executable identity; it is not a remote build proof.

## Outcome and limits

- Remote commands, consumed attempt slots and remote workloads: **0 / 0 / 0**.
- Five-pair observer-overhead assessment: **not run**, rather than failed or passed.
- Complete new 300-second workload, generator/collector qualification and all 36
  original workload predicates: **unmeasured**. No failed/missing predicate becomes
  a pass, and no clean-cell/capacity certificate is issued.
- No host state changed; no restoration or release audit is newly claimed.
- Historical Strategy200 remains aborted/invalid with zero common-window
  coverage, 135,913 game-host and 299 bot-host receive-buffer errors. Its exact
  archive hashes and original classifications were preserved in the plan; no
  historical report or analyzer was rewritten.
- Current server capacity, application-delivered inputs, causal bot-host overflow
  mechanism and the historical disconnect cause remain unknown.

This is the plan's **bounded inconclusive** outcome. The local guard prevented an
invalid generator from reaching remote execution. No fix, new budget, timing
retry, ladder, buffer tuning, host provisioning or further workload follows from
this resolution. Any future design/experiment needs a new reviewed bounded plan.
The article remains unblocked by this unknown.
