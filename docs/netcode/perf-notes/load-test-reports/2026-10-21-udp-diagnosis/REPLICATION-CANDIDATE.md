# Candidate: linear stale-cache membership

The frozen [CPU profile](profile-reproduction.md) placed 50.65% of pre-onset
inclusive game CPU in `broadcast_state_updates`. Inspection found that
`DeltaStateCache::cleanup_stale_entities` checked the entire active-ID slice for
every cached entity, once per peer per Snapshot: work proportional to
`cached entities × active entities`. The profile does not separately attribute
that inlined helper, so this candidate needs a remote comparison.

The candidate builds an 8 KiB stack bitmap covering all u16 IDs, then checks
membership while traversing the existing cache. Work becomes proportional to
`active entities + cached entities`, plus a fixed bitmap initialization. Cache
traversal/removal order, removed IDs, remaining cached state, packet scheduling,
wire format, AoI and gameplay settings are unchanged. The cost is 8 KiB of stack
per invocation; it does not allocate a persistent bitmap for every peer.

## Local mechanism timing

Actual `cleanup_stale_entities`, optimized release build, Apple M1 Pro, Rust
1.95.0, thin LTO; 500 consecutive calls per size with all cached entities active.
The manual ignored test `benchmark_stale_cleanup` consumes each result. These
are single bounded observations, not repeated statistical estimates or server
capacity measurements. HashMap layout and host scheduling are not fixed.

| Cached/active entities | Original slice scan, total ms | Rejected HashSet trial, total ms | Bitmap candidate, total ms |
| ---: | ---: | ---: | ---: |
| 256 | 0.948791 | 4.209834 | 0.448875 |
| 1,024 | 14.995584 | 16.767500 | 2.043959 |
| 4,096 | 225.498833 | 58.780125 | 7.570542 |

The HashSet trial reduced the large-set cost but regressed smaller sets and was
not retained or deployed. The bitmap reduced this helper's elapsed time at all
three measured sizes. It does not establish the contribution to total Tick work,
read gaps, or receive-buffer errors.

Reproduction:

```sh
cd rust
cargo test --release -p omega-server benchmark_stale_cleanup -- --ignored --nocapture
```

The local machine's default macOS 27 SDK was incompatible with its Xcode linker;
the successful timing commands set `SDKROOT` to the already installed Xcode
macOS 26.2 SDK for that command only. Remote CAX11 builds use their existing Linux
toolchain. No system SDK selection was changed.

## Validation and next experiment

Regression coverage exercises mixed live/stale cache state, duplicate active IDs,
an active ID absent from cache, repeated cleanup, empty active sets, all entity
bands and both u16 endpoints. Existing broadcast tests cover removal emission.
`cargo test --workspace`, `cargo clippy --workspace --all-targets`,
`cargo fmt --check`, and the client extension build passed; existing Clippy
warnings remain. The manual performance test stays ignored in ordinary test runs.

Prediction: at the same Strategy population and valid offered input, this change
reduces replication/Tick work and socket read gaps; if those gaps trigger loss and
ACK queue amplification, it should also reduce receive drops and late transport
CPU. If drops or invalid offered load persist, record that outcome and separate
the remaining transport/generator bottleneck. Keep the instrumented control and
candidate on identical collector settings and bot executable. No buffer tuning
is part of this candidate.
