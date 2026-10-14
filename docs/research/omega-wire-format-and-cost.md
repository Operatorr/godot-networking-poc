# Omega's wire format bit by bit, and its per-player cost

**Status:** Research (issue #27, wayfinder). Verified against the code at commit `62fbfc3`
(branch `research/omega-wire-format-and-cost`, never merged). **Audience:** an article for gamedev
engineers. Every fact below cites the code that owns it. Where a doc disagrees with the code, the code
wins and the drift is listed in [§10](#10-doc-drift-found-while-verifying).

**Method.** I read `rust/protocol`, `rust/server`, `rust/load_test`, the deployed
`deployment/server_config.*.json` and the pinned `rusty_enet 0.4.0` source. I then re-ran both reported
load tests locally (2 bots × 60 s, and the `baseline` scenario: 50 bots × 120 s) with deployed-equivalent
config (`api_server_url` empty, port 8091). For those runs a scratch tally module in the bot swarm
classified every received packet by type, and every snapshot record by entity kind and mask, using the
real `protocol` encoder. The scratch code isn't committed; its raw output is in the
[Appendix](#appendix-raw-tally-from-the-local-50-bot-run). Line numbers are for `62fbfc3`.

Terms follow [`docs/CONTEXT.md`](../CONTEXT.md): **Tick**, **Snapshot**, **Baseline**, **AoI**,
**Game event**, **Local player**, **Remote entity**.

---

## TL;DR

- **Input:** 22 bytes at 30 Hz, all byte-aligned. Upstream is a fixed 660 B/s per player, even when the
  player is idle.
- **Snapshot:** a 16-byte delta header, then LSB-first bit-packed records. A moving player costs
  **49 bits** a Tick, a projectile **54 bits**, a monster **53 bits**. Positions are absolute 16-bit
  values at 0.1 u, truncated toward zero. "Delta" means a 5-bit change mask over *absolute* values,
  measured against the last state *sent* (not acked). A Baseline goes out every 100 Ticks.
- **Where the bytes go (50 bots):** the average delta Snapshot is **384 B**. **65%** of it is
  projectiles. Projectiles are re-sent every Tick even though their flight is deterministic.
  Players are 30%. Monsters are almost absent because 50 bots kill them on sight.
- **Measured breakdown of 13.7 KB/s down per bot:** snapshots 83%, Game events 12% (mostly the
  12-byte `PROJECTILE_FIRED`), and ActionConfirm 3.5% (16 B every Tick).
- **AoI and broadcast:** Game events are broadcast to every peer. They aren't AoI-filtered or budgeted.
  The AoI (1000 u enter, 1100 u exit) is half the Arena's width, so on average a bot sees about 42% of
  everything.
- **Cost model:** per-recipient bytes grow linearly in N, so total egress grows as N². That holds until
  the 1200 B per-Snapshot budget bites, which the model puts at about 165 players. After that, broadcast
  events keep growing without limit.
- **14.85 KB/s against the 5 KB/s gate:**
  - The gate sums both directions. Fixed costs alone are about 1.8 KiB/s (input up, plus header,
    ActionConfirm and own record down).
  - The rest is about 36 visible projectiles and about 17 player records per Tick, plus about 4.4
    broadcast events per Tick.
  - Roughly 3% is a measurement artifact from the spawn ramp.
  - The server's byte budget (36 KB/s) has no relation to the 5 KB/s gate.
- **32.9 Hz:** the server ticks at exactly 30 Hz. The estimator divides the tick span (which includes
  the ~11.6 s spawn phase) by the fixed 120 s run window. 30 × 131.6 / 120 = 32.9. Locally the spawn
  phase was 5.4 s, giving 31.3 Hz, and the arithmetic matches exactly.

---

## 1. Framing and bit packing

- **No length field.** ENet preserves datagram boundaries, so every packet is `[u8 type][payload]`
  (`rust/protocol/src/lib.rs:8-11`). Type ids: client to server 1–6, server to client 64–68. The two
  ranges are disjoint, so a misrouted packet can't alias another type (`rust/protocol/src/types.rs:6-22`).
- **Integers are little-endian.** Bit fields are packed **LSB-first** by `BitWriter::write_bits`
  (`rust/protocol/src/bits.rs:26-39`).
- **Byte writes re-align.** Every byte-sized write (`write_u8/u16/i16/u32`) first pads the current
  partial byte with zeros (`bits.rs:45-72`). This is why the input packet and the Snapshot header are
  byte-aligned and only the Snapshot entity records form a true bitstream.
- **Strict decode.** Underflow, bad discriminants or trailing bytes return an error
  (`lib.rs:10-11`, `client.rs:232`).
- **Two quantization rules.**
  - Positions, velocities and cursor: `trunc(v × 10)` clamped to i16, so 0.1 u steps truncated toward
    zero (`rust/protocol/src/quant.rs:8-16`). One consequence is that sub-0.05 u motion never transmits:
    `quant_coord(±0.04) == 0` (`quant.rs:57-62`).
  - Angles: `trunc(rad × 100)`, so 0.01 rad (`quant.rs:22-27`).
  - Stamina, mana and cooldowns use round-half-away-from-zero into a u8 (`quant.rs:35-46`).

## 2. (a) The client input packet: `PlayerInput`, type 2, ch2, 22 bytes

Encoder: `rust/protocol/src/client.rs:153-165`. Struct: `client.rs:82-94`. It's fully byte-aligned
and has **no bit packing**.

| Byte | Field | Width | Encoding | Why it's there |
|---|---|---|---|---|
| 0 | type = 2 | 8 bits | u8 | Packet discriminant (`types.rs:8`) |
| 1 | `sequence` | 8 bits | u8, wraps at 256 | Input sequence for Reconciliation. Echoed in ActionConfirm (`server.rs:222`) |
| 2–3 | `input_flags` | 16 bits | u16 LE bitfield | Bits 0–8 are used: UP, DOWN, LEFT, RIGHT, SHOOT, ABILITY, SPRINT, INTERACT, DASH (`types.rs:104-114`). Bits 9–15 are free, so 7 bits are wasted every packet |
| 4–5 | `aim_angle` | 16 bits | i16, rad × 100, trunc | Aim direction. ±π only needs ±315, which fits in 10 bits |
| 6–9 | `position` x, y | 2 × 16 bits | i16, 0.1 u, trunc | The client's *predicted* position. The server validates it against thresholds (contract.md §PlayerInput) |
| 10–13 | `velocity` x, y | 2 × 16 bits | i16, 0.1 u/s, trunc | Predicted velocity |
| 14–17 | `cursor` x, y | 2 × 16 bits | i16, 0.1 u, trunc | Mouse world position, the ability target (protocol v4). Sent every Tick but only read on the Tick an ability fires (`client.rs:88-91`) |
| 18–19 | `client_render_tick` | 16 bits | u16 | Low 16 bits of the server Tick at which Remote entities were drawn. Input to Lag compensation |
| 20–21 | `client_rtt_ms` | 16 bits | u16 | Client's ENet RTT |

**Cost.** The client sends one input per Tick: the bot at `--input-hz` default 30 (`load_test/README.md`),
and the Godot client at `INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`
(`client/scripts/network/prediction.gd:83`). That's **22 × 30 = 660 B/s upstream of application
payload**. The tally measured 660.0 B/s (Appendix, `tx type 2`). The packet rides ch2, unreliable
sequenced (`client.rs:119-129`). The server drains *all* queued inputs each Tick but steps the
simulation once (`rust/server/src/sim/player.rs:686-711`).

**Packing headroom (observation, not implemented).**
- Flags need 9 bits, the angle 10, and the cursor isn't needed on most Ticks.
- An Arena coordinate (±1000 at 0.1 u) needs 15 bits, not 16.
- A bit-packed input with the cursor sent only when ABILITY is set would be about 13–14 B.

## 3. (b) The Snapshot, type 65

### 3.1 Header (byte-aligned)

Encoder: `rust/protocol/src/snapshot.rs:199-212`.

| Field | Width | Notes |
|---|---|---|
| type = 65 | u8 | |
| `server_tick` | u32 | The full Tick counter |
| `server_ms` | u32 | Server monotonic ms, wrapped to u32. This is the relocated clock-sync heartbeat (`snapshot.rs:15-16`) |
| flags | u8 | bit0 `IS_DELTA`, bit1 `BASELINE` (`types.rs:147-150`). Both set is rejected (`snapshot.rs:251-253`) |
| `baseline_tick` | u32 | **Only if `IS_DELTA`** |
| `entity_count` | u16 | Decode caps it at 4096 (`types.rs:53`, `snapshot.rs:259-261`) |

So a **delta header is 16 B** and a **Baseline header is 12 B**. The 12-byte figure is pinned by
`snapshot.rs:466-482`. The record bitstream follows the header, and the final byte is zero-padded
(`snapshot.rs:242`).

### 3.2 Typed entity id (bit-level)

`[2-bit kind][offset]` (`snapshot.rs:103-130`). The kind replaces the old `u16 id + u8 type`:

| Kind | Entity | Offset bits | Id range | Id bits total |
|---|---|---|---|---|
| 0 | player | 10 | 1–999 (id = offset) | **12** |
| 1 | projectile | 15 | 10000–29999 (offset = id − 10000) | **17** |
| 2 | monster | 14 | 30000–39999 | **16** |
| 3 | world effect (healthorb, mine, dot-zone, bible) | 14 | 40000–49999, in four 2500-id sub-bands by subtype (`types.rs:58-70`) | **16** |

### 3.3 Record layouts

- **Baseline record** (`snapshot.rs:213-218`): `[typed-id][3-bit anim][16-bit entity_flags][16-bit qx][16-bit qy]`.
- **Delta record** (`snapshot.rs:220-240`): `[typed-id][5-bit mask]`, then fields selected by the mask:
  - bit0 POSITION → `qx, qy` (32 bits)
  - bit1 ANIMATION → 3 bits
  - bit2 FLAGS → 16 bits
  - bit3 REMOVED → nothing
  - bit4 FULL → anim, flags, qx, qy (51 bits)
  - Decode precedence is FULL before REMOVED (`snapshot.rs:270-275`).
  - **Mask-0 entities are never encoded** (`rust/server/src/net/broadcast.rs:674-676`).
- **`anim`** is 3 bits with values 0–6 (`types.rs:92-101`). For projectiles it's the flight octant, which
  is constant per projectile (`world.rs:619`).
- **`entity_flags`** is 16 bits. Bits 0–9 are used (ALIVE … STEALTH) and 10–15 are reserved
  (`types.rs:118-133`).

The **exact bit cost of every record shape** comes from `EntityRecord::wire_bits`
(`snapshot.rs:74-100`, used by the byte budget). Every average below was confirmed by the tally:

| Record | Player | Projectile | Monster / world effect |
|---|---|---|---|
| Baseline (full) | 12+3+16+32 = **63** | **68** | **67** |
| Delta FULL | 12+5+51 = **68** | **73** | **72** |
| Delta POSITION only | 12+5+32 = **49** | **54** | **53** |
| Delta POSITION+ANIM | 52 | 57 | 56 |
| Delta POSITION+FLAGS | 65 | 70 | 69 |
| Delta POS+ANIM+FLAGS | 68 (equals FULL) | 73 | 72 |
| Delta REMOVED | **17** | **22** | **21** |

A moving entity therefore costs about 6–7 bytes per Tick, and the 16-bit absolute position is 60–65% of
that record.

### 3.4 Delta scheme as built

The scheme is a change mask over absolute values against the last *sent* state:

- **What "delta" means.** Every field on the wire is **absolute**: a full quantized position, the full
  flags word. A "delta" only *omits* fields that haven't changed. There's no arithmetic or XOR delta.
- **The per-peer cache.** Each peer has a `DeltaStateCache` holding the last `{position, animation,
  flags}` that was *sent* (`broadcast.rs:47-63`).
- **How the mask is chosen** (`calculate_delta_mask`, `broadcast.rs:66-89`):
  - FULL if the entity is new to this peer.
  - FULL if the 100-Tick Baseline interval has elapsed (`DELTA_FULL_STATE_INTERVAL = 100`,
    `broadcast.rs:18`).
  - Otherwise POSITION if either axis moved by ≥ `POSITION_EPSILON = 0.05` (half a quantization step,
    `broadcast.rs:21`), plus ANIMATION or FLAGS on any change.
- **Cache update.** The cache is updated **on send, per admitted field** (`update_cache_partial`,
  `broadcast.rs:108-133`; called at `broadcast.rs:738-742`). It isn't updated on ack.
  - A lost delta self-heals for anything that keeps changing, such as positions of moving entities.
  - A lost one-off flag or animation change stays stale until the next Baseline, up to 100 Ticks
    (3.3 s).
- **Baselines.**
  - Every 100 Ticks the peer gets a full Snapshot on **ch1 reliable** (`server.rs:192-206`), with
    `BASELINE` set and no byte budget (`create_full_state_packet`, `broadcast.rs:604-628`).
  - The client acks with `BaselineAck` (5 B). If no ack arrives within 30 Ticks, the Baseline is resent
    (`BASELINE_ACK_TIMEOUT_TICKS`, `broadcast.rs:19, 157-163`).
  - The ack only clears the resend timer. `acked_baseline_tick` is written but never read
    (`broadcast.rs:170-177`).
  - Deltas carry `baseline_tick = ` the last *sent* Baseline (`broadcast.rs:751`). See
    [§10](#10-doc-drift-found-while-verifying).
- **A side effect worth knowing.**
  - A Baseline is only sent on a Tick with **no AoI removals** for that peer
    (`needs_baseline && removed_entity_ids.is_empty()`, `broadcast.rs:487`).
  - Until such a Tick comes, the delta path runs with the interval expired. `calculate_delta_mask`
    then returns FULL for *every* visible entity, changed or not.
  - At 50 bots a peer sees about 1.36 projectile removals per Tick, so this all-FULL window lasts
    about 3–4 Ticks per cycle.
  - It shows in the tally as 0.83 player FULL records per delta, which is far more than AoI entries
    alone would produce. The cost is about 1% of downstream.

### 3.5 AoI, LOD and the byte budget

Code: `broadcast.rs:377-530`. Live values are in `deployment/server_config.arena.json` and the
`config.rs:45-76` defaults.

- **Radius with hysteresis.**
  - Enter at `aoi_radius = 1000`, exit at `aoi_exit_radius = 1100`. The test is a strict `>`, so an
    entity exactly on the radius stays visible (`broadcast.rs:436-457`).
  - A peer's own entity is never culled (`broadcast.rs:442-463`).
  - Entities that leave AoI become **pinned** REMOVED records (`broadcast.rs:649-667`). So do stale
    cache entries (`broadcast.rs:714-734`). Pinned records bypass the budget and still count against it
    (`broadcast.rs:290-295`).
- **Broad phase.** One `SpatialGrid` is built per Snapshot Tick with cell size `exit_radius / 4 = 275`
  (`broadcast.rs:407-415`). Each peer queries its exit radius in that grid.
- **LOD is a priority penalty, not a send rate.** Distance bands are ≤400 / ≤1000 / beyond, with
  penalties 0 / 4 / 8 (`broadcast.rs:30, 365-373`). Priority is importance plus ticks since last
  sent, minus the LOD penalty, plus a change bonus. Importance is player 10, projectile 8, monster or
  world effect 4 (`broadcast.rs:26-29, 248-276, 700-708`).
- **Byte budget.** The per-peer cap is `clamp(bandwidth_budget_bps / snapshot_rate, 256, max_snapshot_bytes=1200)`
  (`rust/server/src/sim/world.rs:298-310`; `MIN_SNAPSHOT_FLOOR = 256` at `world.rs:45`).
  - Both the bot and the Godot client advertise 0 or 120000, so 120000 / 30 = 4000, clamped to
    **1200 B per Snapshot** (`load_test/src/bot.rs:280` with the default 0;
    `client/autoload/network_manager.gd:62`).
  - The value is effectively **bytes**/s despite the `bps` name (no division by 8).
  - The budget counts **record bits only**. The 16-byte header and the pinned removals sit on top
    (`broadcast.rs:286-301`).
  - Admission is greedy in priority order and has no early break (`broadcast.rs:278-302`).
  - **At 50 bots the budget never engaged.** The largest delta was 1057 B, so records were ≤ 1041 B,
    under the 1200 B of record budget.
- **What's on the entity list** (`world.rs:603-641`):
  - authenticated players, including dead ones
  - alive projectiles
  - all monsters, including dead-pending-cleanup
  - alive world effects
- **How much the AoI culls in the Arena.** The Arena is 2000 × 2000 u (`AGENTS.md` invariants), and the
  AoI disc covers up to 78.5% of it from the center. Measured from 1,739 Baselines at 50 bots, a bot
  sees on average **21.4 players (including itself) and 35.7 projectiles**. That's about 42% of the
  Instance. It's lower than the geometric maximum because wandering bots drift to the walls and
  corners. **In this Arena the AoI is a modest cull, not interest management in the MMO sense.**

## 4. The other per-Tick and broadcast packets

| Packet | Bytes | Who gets it | Rate | Code |
|---|---|---|---|---|
| `ActionConfirm` (66, ch0 unreliable) | **16** | Owner only | One per Tick in which any input arrived. With 30 Hz inputs that's about 30/s | `server.rs:221-233`; `world.rs:444-489` |
| `PROJECTILE_FIRED` (67/12, ch1 reliable) | **12** | **All peers (broadcast)** | Every shot, from players and monsters | `world.rs:702-712`; `world.rs:529-540` (monster shots carry x = y = 0, tick 0) |
| `DAMAGE` (67/1) | 9 | All peers | Per hit | `combat.rs:155, 302` |
| `KILL` / `KILL_PVP` (2/10) | 6 | All peers | Per kill | `combat.rs:195, 215, 317` |
| `RESPAWN` (3) | 10 | All peers | Per respawn | `world.rs:408-416` |
| `EXP_GAIN` (13) | 8 | All peers | One per nearby player per monster kill | `combat.rs:358` |
| `PLAYER_INFO` (9) | 11 + name | All peers | Join, hydrate, level-up | `world.rs:369-390`; `combat.rs:397` |
| `LEADERBOARD_UPDATE` (11) | 7 + 6·rows (≤10 rows, so 67) | All peers | On any kill (coalesced to one per Tick), and every 5 s | `world.rs:44, 574-580`; `server.rs:283-291` |
| `PROGRESS` (15) | 13 | Owner | XP changes | `combat.rs:381`; `server.rs:311-319` |
| `SERVER_METRICS` (68) | 34 | All peers | 1 Hz | `main.rs:317-335`; `server.rs:326-340` |

**Game events are never AoI-filtered or budgeted.** `outbox.broadcast` sends to every connected peer
(`rust/server/src/net/outbox.rs:47-50`; `main.rs:406-419`). Every peer therefore pays for every shot
fired anywhere in the Instance. That makes events an O(N)-per-recipient term no matter how small the
AoI is.

## 5. (c) Channel plan and ENet per-datagram overhead

**Channels** (`lib.rs:53-56`; `server.rs:192-206`; `client.rs:119-129`):

| Ch | ENet mode | Server to client | Client to server |
|---|---|---|---|
| 0 | unreliable **sequenced** (`Packet::unreliable` = `sequenced: true`, rusty_enet `packet.rs:91-93`) | delta Snapshots, ActionConfirm | — |
| 1 | reliable ordered | Baselines (incl. full-state replies), AuthResult, every GameEvent, ServerMetrics | ConnectAuth, BaselineAck, RequestFullState, RespawnRequest, LocalHitReport |
| 2 | unreliable sequenced | — | PlayerInput |

**ENet framing.** Source: `~/.cargo/registry/src/index.crates.io-*/rusty_enet-0.4.0/src/`. The host is
created with defaults: no checksum and no compressor (`host.rs:48-60`; server `main.rs:187-195`; bot
`bot.rs:114-118`). One UDP datagram looks like this:

```
[IPv4 20 + UDP 8]                                  28 B (IPv6: 48 B)
[ENet header: u16 peer_id|flags]                    2 B
  [+ u16 sent_time]                                 +2 B only if the datagram carries a reliable command
[command]*  each = 4 B command header + per-type fields + payload
```

| ENet command | Header bytes | Source |
|---|---|---|
| Protocol header | 2, or 4 with `sent_time` | `c/protocol.rs:62-65`; size chosen at `c/protocol.rs:2202-2211`; `SENT_TIME` set when a reliable command is included at `c/protocol.rs:1988-1990` |
| `SEND_UNRELIABLE` (ch0, ch2) | 4 + 2 seq + 2 len = **8** | `c/protocol.rs:149-153`; selection at `c/peer.rs:267-269` |
| `SEND_RELIABLE` (ch1) | 4 + 2 len = **6** | `c/protocol.rs:143-146`; `c/peer.rs:261-266` |
| `ACKNOWLEDGE` (per reliable command received) | **8** | `c/protocol.rs:75-79` |
| `SEND_FRAGMENT` | 24 | `c/protocol.rs:163-171` |

**Bundling and fragmentation.**
- ENet packs every queued command for a peer into datagrams up to the MTU when the host flushes. The
  server calls `host.flush()` once after each Tick (`main.rs:308-315`). So a Tick's delta Snapshot,
  ActionConfirm and Game events normally leave in **one datagram**.
- The default MTU is 1392 (`consts.rs:32`). The *fragmentation* threshold is the MTU minus the 4-byte
  header minus the 24-byte fragment header, which is **1364 B of payload** (`c/peer.rs:181-188`).
- An unreliable packet above that threshold becomes reliable fragments (`c/peer.rs:207-221`). The 1200 B
  cap leaves about 150 B of margin.
- The sender can also *drop* unreliable commands under its packet throttle when RTT degrades
  (`c/protocol.rs:1998-2004`).

**Overhead at 50 bots.** These are computed from the measured packet mix of about 4.4 reliable Game
events per Tick per bot:

- **Downstream, per Tick per peer:** 28 (IP/UDP) + 4 (header with sent_time) + 8 (snapshot command)
  + 8 (confirm command) + 6 × 4.4 (event commands) ≈ **74 B per Tick ≈ 2.2 KB/s**. That's about
  **+16%** on top of the 13.7 KB/s application payload.
- **Reliable events are the expensive kind.** A 12-byte `PROJECTILE_FIRED` carries a 6-byte command
  header (+50%), and the client must return an 8-byte ACK for it.
- **Upstream, per player:**
  - Each input datagram is 28 + 2 + 8 + 22 = **60 B, so 1.8 KB/s on the wire against 660 B/s of
    payload**.
  - ACKs add 8 B × about 132 reliable commands/s ≈ **1.05 KB/s**.
  - In practice ENet sends ACKs during `host.service()` as soon as it's called, and the bot polls
    every 1 ms. So ACKs often go out in their own datagrams, which adds about 30 B per ACK datagram on
    top.
  - This upstream analysis is source-derived. No harness captures it ([§9](#9-g-what-the-load-test-measures-and-how)).

**None of the reported KB/s include any of this.** The server counts `bytes.len()` of the encoded
application packet (`main.rs:401, 416`). The bots count `packet.data().len()` and `bytes.len()`
(`load_test/src/bot.rs:296, 611`).

## 6. (d) Where the bytes go

Local `baseline` run (50 bots, default behavior). The figures are for the 120 s run phase, per bot per
second, downstream application payload, **13,687 B/s** total. The run's own report showed 14.25 KB/s;
the gap is the spawn ramp, explained in §8.

| Item | B/s per bot | Share of downstream | Notes |
|---|---|---|---|
| **Delta Snapshots** | **11,410** | **83.4%** | 29.7/s, **avg 384 B**, max 1057 B |
| … projectile records | 7,466 | **54.5%** | per delta: 33.1 pos-only (54 b) + 2.6 FULL (73 b) + 1.4 REMOVED (22 b) |
| … player records | 3,399 | 24.8% | per delta: 9.4 pos-only (49 b) + 6.5 pos+anim/flags (avg 61 b) + 0.8 FULL (68 b) |
| … 16 B delta header | 475 | 3.5% | |
| … monster and world-effect records | 57 | 0.4% | bots wipe monsters out (0.25 visible) |
| … padding | 13 | 0.1% | under 1 byte per Snapshot |
| Baselines (ch1) | 142 | 1.0% | 0.29/s, avg 488 B |
| **ActionConfirm** | **475** | **3.5%** | 16 B × ~30/s |
| **Game events** | **1,627** | **11.9%** | 132 events/s |
| … `PROJECTILE_FIRED` | 1,125 | 8.2% | 93.8/s × 12 B: *every* shot in the Instance |
| … `LEADERBOARD_UPDATE` | 151 | 1.1% | 2.3/s × 67 B |
| … `DAMAGE` / `EXP_GAIN` / `PLAYER_INFO` / `RESPAWN` / `KILL_PVP` / other | 147 / 100 / 65 / 21 / 13 / 4 | | |
| SERVER_METRICS | 34 | 0.2% | |

**Why the average delta is 384 B.** 16 B header + (16.7 player records × 54.7 bits + 37.1 projectile
records × 54.2 bits + 0.27 monster records × 53 bits) / 8 ≈ 16 + 367 = **383 B**. That matches the
measured 384.1 B.

The big items, in order:

1. **Projectiles are re-sent every Tick.**
   - A projectile always moves (400 u/s, so 13.3 u per Tick; `sim_core/src/constants.rs:110`). That's
     far above the 0.05 u epsilon, so every visible projectile costs a 54-bit position record on
     every Tick: **202.5 B/s per visible projectile, per viewer**.
   - Its flight is deterministic once you know origin, direction, speed and fire Tick. For player
     shots the `PROJECTILE_FIRED` event already carries origin and fire Tick (`world.rs:702-712`).
   - So the protocol pays twice: once for the reliable event and again for per-Tick positions for the
     projectile's whole life. Bullet life is 560 u (Warrior, Rogue) or 800 u (Mage), so 1.4–2.0 s
     (`rust/server/src/sim/ability.rs:241, 268, 293`). Hits and walls cut that to about 0.9 s on
     average here.
2. **Player records are absolute 32-bit positions every Tick.** Bots also flicker SHOOT at random
   (20% per frame, `load_test/src/behavior.rs:199, 209-221`). SHOOT drives both the ATTACK animation
   and the ATTACKING flag (`player.rs:386-412`), so about 40% of player records carry an extra
   3 + 16 bits. A human holding the fire button would toggle far less often. This part is a bot
   artifact.
3. **Fixed per-player traffic is about 1 KB/s down, before any other entity.** That's the header
   (475), ActionConfirm (475), the player's own record (~180–200) and SERVER_METRICS (34).
4. **Broadcast Game events** cost about 30 B/s per player in the Instance for every recipient.

## 7. (e) Cost model

### 7.1 Per recipient, per Tick (application payload)

For one recipient, with `V_p` visible other players, `V_j` visible projectiles, `V_m` visible moving
monsters, and global event rates `S` (shots/s), `D` (damage/s) and so on:

```
B_tick ≈ 16                                    delta header
       + 16                                    ActionConfirm (if an input arrived this Tick)
       + ceil( b_self                          own record, 49–68 bits
             + Σ_players   (49 + 3·[anim Δ] + 16·[flags Δ])   only players whose mask ≠ 0
             + 54 · V_j                         every visible projectile, every Tick
             + 53 · V_m                         every visible moving monster
             + 73·new_j + 68·new_p + 72·new_m   AoI entries / spawns (FULL)
             + 22·rem_j + 17·rem_p + 21·rem_m ) / 8   AoI exits / despawns (pinned)
       + (12·S + 9·D + 8·X + 6·K + 10·R + 27·I + 67·L) / 30   broadcast Game events (all peers)
       + 34/30                                 SERVER_METRICS
```

Every 100th Tick a Baseline (`12 + ceil((63·(V_p+1) + 68·V_j + 67·(V_m+V_w)) / 8)`) replaces that
Tick's delta on ch1. Bytes per second is **30 × B_tick**. Snapshot rate equals Tick rate, 30 Hz:
`snapshot_rate_hz = 30` in `deployment/server_config.arena.json` and `config.rs:81-87`.

The **delta part** (header + records) is capped at about **1216 B per Tick** (1200 B budget on records +
16 B header + pinned removals). That puts snapshots at at most **≈ 36.5 KB/s**. ActionConfirm and Game
events sit **outside** the cap.

### 7.2 Per-second coefficients measured at 50 bots

| Term | Cost per recipient |
|---|---|
| Fixed (header + ActionConfirm + metrics + own record) | ≈ **1.17 KB/s** down, + **0.66 KB/s** up |
| Each visible other player | ≈ **157 B/s** (78% of visible players change each Tick; avg 54.7 bits) |
| Each visible projectile | ≈ **209 B/s** (202.5 for position + amortized FULL/REMOVED) |
| Each visible moving monster | ≈ **199 B/s** |
| Each player in the Instance (broadcast events, AoI-blind) | ≈ **30 B/s** (dominated by 12 B × ~1.9 shots/s) |

### 7.3 Scaling with N in this Arena

The Arena has fixed size and the AoI covers about 42% of it, so `V_p ≈ 0.42·(N−1)` and
`V_j ≈ 0.42·N·s·L`. Here `s·L ≈ 1.7` projectile-seconds per player (measured, default bots):

```
R(N) ≈ 1.3 KB/s + 0.42·(N−1)·157 + 0.42·N·1.7·209 + 30·N      [B/s, downstream]
     ≈ 1.3 KB/s + ~245 B/s · N
E(N) = N · R(N)  → quadratic total egress
```

| N | R(N) down | Avg delta | Events | Total egress (payload) |
|---|---|---|---|---|
| 2 | ~1.8 KB/s* | ~35 B | 0.06 KB/s | — |
| 50 | **13.5 KB/s** (measured 13.7) | ~380 B (measured 384) | 1.5 KB/s | ~0.68 MB/s |
| 100 | ~26 KB/s | ~740 B | 3 KB/s | ~2.6 MB/s |
| ~165 | snapshots hit the 1200 B budget; the scheduler starts deferring | ~1216 B | ~5 KB/s | |
| 500 | snapshots capped ≈ 36.5 KB/s **+ events ≈ 15 KB/s** | capped | 15 KB/s | ~26 MB/s |
| 1000 | snapshots capped ≈ 36.5 KB/s **+ events ≈ 30 KB/s** | capped | 30 KB/s | ~67 MB/s |

\* At small N, monsters dominate. They survive when few players are hunting them, so plug the measured
`V_m` and `V_j` into §7.1 rather than using the N-scaling.

Caveats:
- The scaling rows past 50 are an **extrapolation** from coefficients measured at N = 50. Nothing was
  run above 50.
- The 42% visibility and `s·L` depend on bot behavior and Arena size.
- The structural conclusions don't depend on those numbers:
  1. In this Arena per-recipient cost is linear in N until the budget caps snapshots.
  2. Broadcast Game events grow without bound, as O(N) per recipient and O(N²) in total, even after
     snapshots are capped.

Wire bytes add about 16% downstream on top of these payload figures (§5).

## 8. (f) Checking the model against the two reports

### 8.1 Two bots, local: 3.01 KB/s, server 2911 B/s per client, 0.12 ms tick, 5 entities

- **Upstream:** 662 B/s.
- **Downstream, from the model:** fixed ≈ 1.0 KB/s + self and one other player ≈ 0.24 KB/s + the
  5 non-player entities (projectiles and monsters, ~200 B/s each if visible, so ≤ 1.0 KB/s) + events
  (~0.1 KB/s) + Baselines (~0.04 KB/s). That's about 2.3–2.4 KB/s.
- **Total:** about 3.0 KB/s, in line with the report's **3.01 KiB/s** (3,082 B/s).
- **My two local 2-bot runs** gave **3.09 and 4.04 KiB/s**. The difference was entirely monsters:
  0.78 against 2.86 visible per delta. At N = 2 the bill is dominated by however many monsters and
  their shots happen to be near.
- **Server-reported 2911 B/s** is a single 1-second sample (§9). It falls inside that variance.
- **Tick:** 0.12 ms on the droplet, 0.09 ms locally.

### 8.2 Fifty bots, live: 14.85 KB/s, 16,211 B/s server, 3.00 / 4.11 ms tick, 51 players, 89 entities

**Reproduced locally** with the same scenario: **14.25 KiB/s**, server 13,904 B/s, 2.13 / 3.01 ms
tick, 50 players, 84 entities, 31.3 Hz estimated, 1,179,505 packets received / 186,272 sent.

- **Packet counts.**
  - Received: 1,225,513 / 50 bots ≈ 24.5 k packets per bot ≈ **~193 ENet packets/s**. That's 30
    Snapshots + 30 ActionConfirms + ~132 Game events + 1 SERVER_METRICS, which matches the local mix.
    These are ENet *packets* (messages). Datagrams are about 30/s per peer because of bundling.
  - Sent: 190,673 / 50 ≈ 3,813 per bot. That's inputs at 30/s over each bot's ~125 s connected life
    (3,600 in the run window + the spawn ramp), plus ~37 BaselineAcks and a few hit reports and
    respawns.
- **Bytes.**
  - 14.85 KiB/s × 1024 × 50 × 120 s = 91.2 MB summed across bots. Minus ~4.15 MB upstream
    (190,673 × ~21.8 B) that leaves about **87.1 MB received**.
  - The server's lifetime `total_bytes_sent` is **88,581,168**. The extra ~1.5 MB is about what the
    51st (non-bot) client would have received over the run. So the counter is consistent with a
    freshly started server, and with ≈ 51 × 13.9 KB/s × 125 s.
- **The model at N = 51** gives ≈ 13.8 KB/s down + 0.68 KB/s up ≈ **14.2 KiB/s** steady-state. Add the
  spawn-ramp inflation (below, ≈ +0.4 KiB/s for an 11.6 s ramp) and you get about 14.6 KiB/s against
  the reported **14.85**, within 2%.
- **Server-reported 16,211 B/s is a single 1-second sample**, taken at the end of the run.
  - `avg_bandwidth_per_client` is the per-peer bytes delta over the last ~1 s
    (`rust/server/src/net/metrics.rs:54-64`), and the report keeps only the latest packet
    (`load_test/src/metrics.rs:191-195, 230-237`).
  - Locally, 5-second windows of swarm receive rate ranged from **12.2 to 15.5 KB/s per bot**, and
    the entity count swung from 62 to 90 within the run (report `time_series`). A 1-s sample swings
    further.
  - 16,211 is a high-side sample. It isn't comparable to the run-averaged bot figure.
- **Tick time.** 3.00 ms avg and 4.11 ms max are over the **last 30 Ticks only** (`METRICS_SAMPLE_SIZE`,
  `server/src/net/metrics.rs:8, 65-71`). That's 9% of the 33.3 ms budget.
  - The figure includes encoding and ENet queue/send work. The Tick timer wraps `world.tick` +
    `flush_outbox` + `host.flush()` (`main.rs:310-314`).
  - The droplet ran about 1.4× slower than the local machine (2.13 ms).
  - CPU isn't the constraint at 50, which matches `docs/server/design.md` ("binding constraint is
    bandwidth, not CPU").

### 8.3 Why 14.85 KB/s against the 5 KB/s budget

1. **The gate counts both directions** (`load_test/src/metrics.rs:206-209`: `(sent + received) / bots
   / duration / 1024`). Upstream input alone is 0.66 KiB/s, 13% of the gate.
2. **Fixed per-player cost is about 1.8 KiB/s** (≈ 1,834 B/s) (input up + header + ActionConfirm + own record +
   metrics down). That's about 36% of the gate before a single other entity is drawn. It comes from
   sending a 22-byte input and a 16-byte ActionConfirm every Tick.
3. **Projectiles are 54.5% of downstream.** About 36 visible, each costing 54 bits every Tick, for
   bullets whose trajectory the client could simulate from the fire event.
4. **The AoI barely culls in this Arena.** A 1000 u radius on a 2000 u map means about 42% of the
   Instance is visible on average.
5. **Game events are broadcast to all peers** with no AoI and no budget, about 1.6 KB/s.
6. **Bot artifacts:**
   - random 20% SHOOT flicker, which inflates player records by about 19 bits on ~40% of them
   - constant random-aim fire, at ~1.9 shots/s per player, including monster shots
7. **A measurement artifact of about 3%** from the spawn ramp (below).
8. **No server mechanism targets 5 KB/s.** The per-peer budget is 1200 B per Snapshot ≈ 36 KB/s, so
   about 7× the gate. Up to about 165 players nothing caps a client's downstream except AoI.

To fit 5 KiB/s at 50 players with today's fixed costs: about 3.2 KiB/s would be left, which is
≈ 110 B per Tick, or about 16 moving records of 54 bits. That's under a third of the ~54 records a bot
currently sees.

### 8.4 Why "32.9 Hz"

- `estimated_server_tick_rate = (max last_server_tick − min first_server_tick) / duration`
  (`load_test/src/metrics.rs:210-220`).
- `min first_server_tick` is the first bot's AuthResult Tick, taken at the start of the **spawn phase**
  (`bot.rs:315`). `duration` is the fixed 120 s run window, even though the span also covers the spawn
  phase and drain (`load_test/src/main.rs:512, 546, 555-566`).
- The server's long-run rate is exactly 30 Hz: fixed-timestep accumulator with remainder carry
  (`main.rs:303-315`; `world.rs:421-434`).
- So **32.9 × 120 / 30 = 131.6 s of Ticks**, which is a 120 s run plus about **11.6 s of spawn**.
  50 bots × (100 ms stagger + per-bot settle, which live includes the signed-ticket HTTPS fetch and an
  auth round trip) explains the 11.6 s.
- Locally the measured spawn phase was 5.4 s and the estimator printed **31.3 Hz**:
  30 × (5.4 + 120) / 120 = 31.35.
- The estimator **over-counts**. The source comment (`metrics.rs:212-217`) and
  `performance-budgets.md` both say it under-counts, which is wrong ([§10](#10-doc-drift-found-while-verifying)).
- The **bandwidth** figure has the same bias: bytes from the spawn ramp and drain sit in the numerator
  over a fixed 120 s denominator. Locally that was 14.25 KiB/s reported against **14.01 KiB/s** in
  the run phase.

## 9. (g) What the load test measures, and how

**Scenarios** (`load_test/src/main.rs:32-90`; README table):

| Scenario | Bots | Duration | Behavior |
|---|---|---|---|
| baseline | 50 | 120 s | default |
| target | 100 | 300 s | default |
| stress | 200 | 300 s | default |
| idle | 100 | 120 s | idle |
| movement | 100 | 120 s | movement |
| combat | 100 | 120 s | combat |
| clustered | 100 | 120 s | clustered |
| strategy | 10 | until Ctrl-C | strategy |

Behavior details (`behavior.rs:196-245`):
- `default` re-picks direction with 10% probability per frame, shoots with 20%, and aims at random.
- `combat` always shoots.
- `clustered` converges on the origin and shoots 30% of the time.
- Bots spawn round-robin as Warrior, Rogue and Mage (`bot.rs:140-145`), send inputs at 30 Hz, and
  advertise bandwidth 0, which the server turns into 120000 (default).

**Each metric and its source:**

| Metric | Side | How it's measured | Gated? |
|---|---|---|---|
| Bandwidth per player | client-estimated | Σ(app bytes sent + received) / connected bots / fixed duration / **1024** (`metrics.rs:206-209`). Payload only, no ENet/UDP. Includes the spawn ramp. | **< 5 KiB/s** (`metrics.rs:14`) |
| Latency avg / p95 | client | ENet's smoothed RTT (`peer.round_trip_time()`), sampled at 1 Hz per bot after 2 s of warm-up (`bot.rs:586-597`) | < 100 / < 150 ms |
| Packet loss | client | ENet's `packet_loss()` / 65536, the last value (`bot.rs:596`). ENet counts *reliable-command timeouts* over *all commands sent* (`c/protocol.rs:1803, 2067, 2180-2195`), measured on the **bot's upstream**. Bots mostly send unreliable inputs, so this barely samples anything, and **downstream Snapshot loss is not measured at all**. | < 2% |
| Crash rate | client | Bots that never reached Running, or were dropped (`metrics.rs:225-229`) | < 5% |
| Tick rate | client-estimated | Tick span / fixed duration. **Over-counts** (§8.4). | ≥ 30 Hz |
| Avg / max tick time | server-reported | Latest SERVER_METRICS. avg/max of the last 30 Ticks (`server/src/net/metrics.rs:65-71`) | no |
| Players, entities | server-reported | Latest SERVER_METRICS. `entity_count` excludes players (`main.rs:321-322`) | no |
| Total bytes out | server-reported | Cumulative since server **start**, u32 (wraps at 4 GiB) (`server/src/net/metrics.rs:30-33, 87`) | no |
| Avg BW per client | server-reported | Bytes sent to all peers over the last ~1 s / peers (`server/src/net/metrics.rs:54-64`). One sample. | no |
| `aoi_cull` | client assertion | Max observed distance to any replicated entity ≤ 1100 + 50 u for 95% of bots (`assertions.rs:13-14, 53-94`) | warn |
| `decode_clean` | client assertion | Zero strict-decode failures (`assertions.rs:96-116`) | warn |
| `per_peer_budget` | client assertion | Downstream bytes/s per bot ≤ `--rate-budget`. Skipped unless set (`assertions.rs:118-150`). | warn |

**Prometheus** (`127.0.0.1:<metrics_port>`, installed with default settings at `main.rs:132-136`):
- gauges: `players_online`, `entities`, `avg_tick_time_ms`, `avg_bandwidth_per_client_bytes`,
  `snapshot_entities_deferred`
- counter: `backstop_hits_total`
- `tick_duration_ms`, exported as a **summary** (quantiles 0 / .5 / .9 / .95 / .99 / .999 / 1 over a
  rolling window). It isn't a histogram, because no buckets are configured. A live scrape showed
  `# TYPE tick_duration_ms summary`.

**What isn't measured:**
- **Wire bytes**, meaning ENet + UDP/IP overhead. That's about +16% downstream and roughly 3–4× the
  upstream payload (§5).
- **Per-packet-type and per-entity-kind byte breakdown.** This research needed a scratch tally to get
  it.
- **Up and down separately in the gated figure**, which is summed. Also **per-bot distributions**:
  the report has per-bot totals but no percentiles.
- **Downstream loss** and **Snapshot gaps** (late, dropped or out-of-order sequenced deltas).
- The scheduler's **`sched_*` fields**. They're on the SERVER_METRICS wire, but the report never
  records them, despite the README claim. Also delta size distribution and how often the budget
  engaged.
- **Server-side RTT**, **CPU per player**, **memory per player**, and tick-time percentiles in the
  report (Prometheus only).
- **Steady-state windows.** Every rate includes the spawn ramp. There's no "after warm-up" figure
  except the 5-s `time_series`.
- **Human-like input.** Bots flicker SHOOT and aim at random, which inflates player-record and
  projectile cost compared with real play.

## 10. Doc drift found while verifying

1. **The contract says deltas only reference an acked Baseline.** `contract.md` §Channels and
   `server.rs:187-191` say "the server only emits deltas against an ACKED baseline". It doesn't.
   - Deltas carry the last *sent* `baseline_tick` (`broadcast.rs:751`).
   - The delta cache is reset when the Baseline is sent (`broadcast.rs:618-620`).
   - `acked_baseline_tick` is never read (`broadcast.rs:170-177`).
   - The ack only cancels the 30-Tick resend.
   - In practice this is benign: every field is absolute, so an early delta applies correctly. But the
     ordering guarantee as written doesn't exist.
2. **`contract.md` GameEvent tails drifted from the code.**
   - `ABILITY_EFFECT` is `[u8 effect_id]`, not u16 (`server.rs:306`).
   - `PROGRESS` is `[u8 move_speed_q]`, not s16 (`server.rs:318`). The measured PROGRESS event is
     13 B.
   - `types.rs:170-177` matches the code.
3. **`performance-budgets.md` misidentifies the pinned entries.** It says "pinned items (the player's
   own entity) bypass the budget". Pinned entries are **REMOVED records only** (`broadcast.rs:649-667,
   714-734`). The peer's own entity goes through the scheduler like any other candidate.
4. **The tick-rate estimator over-counts.** `performance-budgets.md` and the comment at
   `load_test/src/metrics.rs:212-217` both call it a "mild under-count". It's an over-count by
   (spawn + drain) / duration (§8.4).
5. **`performance-budgets.md`'s "tick_duration_ms histogram"** is a Prometheus **summary** (§9).
6. **The `load_test/README.md` claim about scheduler fields is wrong.** It says "Scheduler health is
   visible in the `sched_*` fields of SERVER_METRICS captured in every report". The report keeps only
   six server fields (`load_test/src/metrics.rs:230-237, 414-421`).
7. **`bandwidth_budget_bps` is used as bytes/s.** It's divided by the Snapshot rate with no
   division by 8 (`world.rs:298-310`).
8. **"The per-peer byte budget enforces < 1200 B" (`contract.md`) is not exact.**
   - The budget covers record bits only, so a full-budget delta is 1216 B plus any pinned removals.
     That would trip the oversized warning at `main.rs:382-389`.
   - The real ENet fragmentation threshold is 1364 B of payload, not the 1392 MTU.
   - ENet bundles the ActionConfirm and events into the same datagram anyway.

## 11. Open questions (not resolved here)

- **How much would client-simulated projectiles save?** Sending only `PROJECTILE_FIRED`, plus REMOVED
  on impact, and dropping per-Tick positions would cut about 54% of downstream at 50 bots. The open
  question is how to keep monster shots consistent: their fire events currently carry x = y = 0
  (`world.rs:529-540`).
- **Should Game events be AoI-filtered or budgeted?** Today they're the only unbounded term past the
  snapshot cap.
- **Real human play is unmeasured.** No load run uses human-like input or a captured human session, so
  the projectile and SHOOT-flicker share for real play is unknown.
- **Nothing has been run above 50 bots.** The ~165-player budget crossover in §7.3 is extrapolated.

---

## Appendix: raw tally from the local 50-bot run

Server: `omega-server --config <arena.json with api_server_url ""> --allow-unsigned-tickets`.
Swarm: `omega-load-test --scenario baseline --server 127.0.0.1:8091`. The scratch tally hooked
`Bot::poll` (on receive, after a successful decode) and `Bot::send` in `rust/load_test/src/bot.rs`.
Records were sized with `EntityRecord::wire_bits`. Spawn phase 5.4 s, run 120.0 s.

```
==== TALLY RUN-PHASE: secs=120.0 bots=50
rx 82120553 B (1155292 pkts) => 13686.7 B/s/bot ; tx 3969022 B (182016 pkts) => 661.5 B/s/bot
delta snaps n=178257 bytes=68460947 (11410.1 B/s/bot, avg 384.1 B, max 1057)
baselines n=1739 bytes=849067 (141.5 B/s/bot, avg 488.3 B)
confirms n=177997 bytes=2847952 (474.7 B/s/bot)
metrics n=5950 bytes=202300 (33.7 B/s/bot)
event type 1: n=98300 bytes=884700 (147.4 B/s/bot, 16.38/s/bot, avg 9.0 B)      DAMAGE
event type 2: n=700 bytes=4200 (0.7 B/s/bot, 0.12/s/bot, avg 6.0 B)            KILL
event type 3: n=12600 bytes=126000 (21.0 B/s/bot, 2.10/s/bot, avg 10.0 B)      RESPAWN
event type 6: n=50 bytes=450 (0.1 B/s/bot, 0.01/s/bot, avg 9.0 B)              PICKUP
event type 9: n=14500 bytes=391500 (65.2 B/s/bot, 2.42/s/bot, avg 27.0 B)      PLAYER_INFO
event type 10: n=12650 bytes=75900 (12.6 B/s/bot, 2.11/s/bot, avg 6.0 B)       KILL_PVP
event type 11: n=13550 bytes=907850 (151.3 B/s/bot, 2.26/s/bot, avg 67.0 B)    LEADERBOARD_UPDATE
event type 12: n=562550 bytes=6750600 (1125.1 B/s/bot, 93.76/s/bot, avg 12.0 B) PROJECTILE_FIRED
event type 13: n=74950 bytes=599600 (99.9 B/s/bot, 12.49/s/bot, avg 8.0 B)     EXP_GAIN
event type 15: n=1499 bytes=19487 (3.2 B/s/bot, 0.25/s/bot, avg 13.0 B)        PROGRESS
delta header bytes=2852112 pad bits=624309
  delta player full: n=148508 (0.83/snap) bits=10098544 (68.0 bits avg) => 210.4 B/s/bot
  delta player removed: n=10430 (0.06/snap) bits=177310 (17.0 bits avg) => 3.7 B/s/bot
  delta player pos-only: n=1675564 (9.40/snap) bits=82102636 (49.0 bits avg) => 1710.5 B/s/bot
  delta player other: n=1157521 (6.49/snap) bits=70770731 (61.1 bits avg) => 1474.4 B/s/bot
  delta proj full: n=465743 (2.61/snap) bits=33999239 (73.0 bits avg) => 708.3 B/s/bot
  delta proj removed: n=242235 (1.36/snap) bits=5329170 (22.0 bits avg) => 111.0 B/s/bot
  delta proj pos-only: n=5908262 (33.14/snap) bits=319046148 (54.0 bits avg) => 6646.8 B/s/bot
  delta monster full: n=2166 (0.01/snap) bits=155952 (72.0 bits avg) => 3.2 B/s/bot
  delta monster removed: n=353 (0.00/snap) bits=7413 (21.0 bits avg) => 0.2 B/s/bot
  delta monster pos-only: n=44565 (0.25/snap) bits=2361945 (53.0 bits avg) => 49.2 B/s/bot
  delta monster other: n=1982 (0.01/snap) bits=105489 (53.2 bits avg) => 2.2 B/s/bot
  delta worldfx full: n=1237 (0.01/snap) bits=89064 (72.0 bits avg) => 1.9 B/s/bot
  delta worldfx removed: n=130 (0.00/snap) bits=2730 (21.0 bits avg) => 0.1 B/s/bot
  baseline player: n=37171 (21.37/baseline)
  baseline proj: n=62109 (35.72/baseline)
  baseline monster: n=457 (0.26/baseline)
  baseline worldfx: n=355 (0.20/baseline)
tx type 2 (PlayerInput): n=180000 bytes=3960000 (660.0 B/s/bot)
tx type 3 (BaselineAck): n=1739 bytes=8695 (1.4 B/s/bot)
tx type 5 (RespawnRequest): n=252 · tx type 6 (LocalHitReport): n=25
delta size hist (100 B buckets): [0, 4707, 39811, 64489, 41602, 17677, 7242, 1793, 571, 326, 39, 0, 0]

Report: Est. Tick 31.3 Hz · Avg/Max tick 2.13/3.01 ms · Players 50 · Entities 84 ·
Total Bytes Out 82827154 · Avg BW/Client 13904 · Packets sent/recv 186272/1179505 ·
Bandwidth/Player 14.25 KB/s · RTT avg 1.6 ms · loss 0.01%
```

The two local 2-bot runs (60 s each) reported 3.09 and 4.04 KiB/s, with 0.78 and 2.86 visible monster
records per delta respectively. In the second run: projectiles 1,514 B/s, monsters 573 B/s, players
239 B/s, ActionConfirm 462 B/s, header 475 B/s, events 121 B/s.
