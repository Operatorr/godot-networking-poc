# The math of replicating realtime state to N players

> **Status:** Reference (research for issue #26, feeds the article tracked by #32 / map #23).
> **Researched:** 2026-10-13. Every constant is cited; derived numbers show their working.
> Terms follow [`../CONTEXT.md`](../CONTEXT.md): a **Tick** is one server sim step, a **Snapshot**
> is one replicated world-state message to one client. Snapshot cadence can differ from Tick cadence.

This is the general background an engineer needs before looking at our numbers. Section 9 has
the worked examples (64, 100 and 1000 players at 30 Hz and 60 Hz). Sections 1–8 derive the
formulas the examples use.

Units: **B** = byte, **b** = bit, **kB** = 1000 B, **Mbit** = 10⁶ bits. All rates are decimal.

---

## 0. Symbols

| Symbol | Meaning |
|---|---|
| `N` | connected players on one server Instance |
| `k` | entities in one client's Snapshot (its "visible set") |
| `b_e` | bits per entity record in a Snapshot |
| `H_s` | Snapshot header bytes (per datagram) |
| `H_d` | per-datagram overhead below the game (IP + UDP + ENet) |
| `f` | Snapshot rate, Hz (Snapshots per second per client) |
| `L` | max game payload per datagram (our rule: 1200 B) |
| `d` | datagrams per Snapshot |

---

## 1. Per-datagram overhead: what each send costs before your first byte

Every datagram carries fixed headers. You pay them per send, not per byte, so they dominate small
packets such as inputs.

### 1.1 IP and UDP

| Layer | Size | Source |
|---|---|---|
| UDP header | **8 B** | RFC 768: four 16-bit fields (source port, destination port, length, checksum); "the minimum value of the length is eight." [RFC 768] |
| IPv4 header (no options) | **20 B** | RFC 791 §3.1: IHL is "the length of the internet header in 32 bit words … the minimum value for a correct header is 5", so 5 × 4 = 20 B. [RFC 791] |
| IPv6 header (no extension headers) | **40 B** | RFC 8200 §3 fixed-header layout: 32 + 32 bits of fields + 128-bit source + 128-bit destination = 320 bits = 40 B. Cross-check, RFC 8200 §8.3: the minimum IPv6 header "is 20 octets longer than a minimum-length IPv4 header", so 20 + 20 = 40. [RFC 8200] |

So `IP+UDP = 28 B` on IPv4 and `48 B` on IPv6. RFC 9000 §14 uses the same figures: "the minimum
IP header size of 40 bytes for IPv6 and 20 bytes for IPv4 and a UDP header size of 8 bytes".
[RFC 9000]

Link-layer framing (Ethernet header, FCS, preamble, inter-frame gap) is **not** included anywhere
below. It is real on the wire, but it is usually not what you provision or pay for at the IP level.

### 1.2 ENet (the transport we run: `rusty_enet` =0.4.0, a transpile of ENet 1.3.18)

`rusty_enet` 0.4 is a C-to-Rust transpile of ENet **1.3.18**, commit `2662c0d`
([rusty_enet README, "ENet Versions" table]). Its structs are `#[repr(C, packed)]` copies of
upstream `protocol.h`. Sizes below are read from
`~/.cargo/registry/src/…/rusty_enet-0.4.0/src/c/protocol.rs` and match upstream
[ENet protocol.h].

| ENet structure | Fields | Size |
|---|---|---|
| `ENetProtocolHeader` | `peer_id: u16`, `sent_time: u16` | **2 B or 4 B.** `sent_time` is only written when `ENET_PROTOCOL_HEADER_FLAG_SENT_TIME` (bit 15) is set. The send path writes `data_length = 2` otherwise (`protocol.rs` ≈ L2202–2211). The flag is set only when the datagram carries a **reliable** command (`protocol.rs` ≈ L1988). |
| optional checksum | `u32` | **+4 B** only if the host has a checksum function installed (`protocol.rs` ≈ L1412). Our server installs none (no `checksum`/`compressor` in `rust/server/src`). |
| `ENetProtocolCommandHeader` | `command: u8`, `channel_id: u8`, `reliable_sequence_number: u16` | **4 B**, on every command |
| `ENetProtocolSendUnreliable` | cmd header + `unreliable_sequence_number: u16` + `data_length: u16` | **8 B** |
| `ENetProtocolSendReliable` | cmd header + `data_length: u16` | **6 B** |
| `ENetProtocolSendUnsequenced` | cmd header + `unsequenced_group: u16` + `data_length: u16` | **8 B** |
| `ENetProtocolAcknowledge` | cmd header + `received_reliable_sequence_number: u16` + `received_sent_time: u16` | **8 B** per ack |
| `ENetProtocolSendFragment` | cmd header + `start_sequence_number`, `data_length` (u16) + `fragment_count`, `fragment_number`, `total_length`, `fragment_offset` (u32) | **24 B** |

Other ENet constants that matter here (`rusty_enet-0.4.0/src/consts.rs`; upstream values match
[ENet enet.h], [ENet protocol.h]):

- `HOST_DEFAULT_MTU = 1392`. ENet's "MTU" is the **ENet-level** datagram (ENet header + commands
  + data). It excludes UDP/IP, so a full ENet datagram is 1392 + 28 = 1420 B of IPv4 (1440 B of IPv6).
- `PROTOCOL_MINIMUM_MTU = 576`, `PROTOCOL_MAXIMUM_MTU = 4096`.
- `PROTOCOL_MAXIMUM_PACKET_COMMANDS = 32`. ENet coalesces up to 32 commands (game packets, acks,
  pings) into one datagram, so the fixed header is shared when a peer has several queued.
- `PEER_PING_INTERVAL = 500` ms. Idle peers still exchange a ping roughly every 0.5 s.
- `PROTOCOL_MAXIMUM_PEER_ID = 4095`. The 16-bit `peer_id` also carries 2 flag bits and 2
  session bits, which leaves 12 bits for the peer, so one ENet host addresses at most 4095 peers.
  That is a hard ceiling per host socket, far above our target.

**Fragmentation threshold** (`src/c/peer.rs` L181–192): a packet is fragmented when
`data_length > mtu − sizeof(ENetProtocolHeader) − sizeof(ENetProtocolSendFragment)`, which is
1392 − 4 − 24 = **1364 B** of game payload. An *unreliable* packet over that size becomes
`SEND_FRAGMENT` (reliable) unless the sender sets `ENET_PACKET_FLAG_UNRELIABLE_FRAGMENT`
(`peer.rs` L207–212). That is the head-of-line-blocking trap that `MAX_UNRELIABLE_PAYLOAD`
guards against (`rust/protocol/src/lib.rs` L58–60).

### 1.3 The per-datagram overhead formula

For one unreliable Snapshot alone in a datagram (no reliable command, so no `sent_time`, and no
checksum):

```
H_d = IP + UDP + ENet header + SendUnreliable
    = 20 + 8 + 2 + 8 = 38 B          (IPv4)
    = 40 + 8 + 2 + 8 = 58 B          (IPv6)
    (+2 B if a reliable command shares the datagram; +8 B per piggy-backed ack)
```

**Overhead fraction** = `H_d / (payload + H_d)`:

| Payload | IPv4 (38 B) | IPv6 with `sent_time` (60 B) |
|---|---|---|
| 22 B (our `PlayerInput`) | 38 / 60 = **63 %** | 60 / 82 = **73 %** |
| 100 B | 38 / 138 = 28 % | 60 / 160 = 38 % |
| 1200 B | 38 / 1238 = **3.1 %** | 60 / 1260 = 4.8 % |

Inputs are mostly header. Snapshots are mostly payload. This explains the up/down asymmetry
in §3.

Historical comparison: Tribes reported its packet-notify protocol "imposes an average overhead of
3 bytes per packet" [Tribes §Connection Layer]. Quake 3's netchan header is a 4 B sequence, plus a
2 B qport client→server and 2 + 2 B fragment fields only when fragmented [Q3 net_chan.c].

---

## 2. Safe MTU and the ~1200 B payload rule

- Ethernet: "the maximum length of an IP datagram sent over an Ethernet is 1500 octets"
  [RFC 894]. 1500 is the common real-world MTU.
- IPv4 only guarantees reassembly: "Every internet destination must be able to receive a datagram
  of 576 octets either in one piece or in fragments to be reassembled" [RFC 791 §2.3]. 576 is a
  reassembly floor. It does not promise that a path will carry the datagram unfragmented.
- IPv6: "IPv6 requires that every link in the Internet have an MTU of 1280 octets or greater"
  [RFC 8200 §5]. A node may "simply restrict itself to sending packets no larger than 1280 octets"
  instead of doing Path MTU Discovery [RFC 8200 §5].
- QUIC turns this into a payload rule: "QUIC MUST NOT be used if the network path cannot support a
  maximum datagram size of at least 1200 bytes". From 1280 − 40 − 8 it derives "a maximum datagram
  size of 1232 bytes for IPv6 and 1252 bytes for IPv4" [RFC 9000 §14].
- Fiedler gives the same game-side advice. His "conservative lower bound on the IPv4 Internet" is
  1200 B, and games use "something like 1000 to 1200 bytes of payload data"
  [Gaffer, Packet Fragmentation].
- Quake 3 used `MAX_PACKETLEN 1400` with `FRAGMENT_SIZE (MAX_PACKETLEN - 100)` [Q3 net_chan.c].

**Derivation for our stack.** The largest game payload that fits the IPv6 minimum link MTU with
ENet framing, worst case (`sent_time` present, no checksum), is:

```
L_max = 1280 − 40 (IPv6) − 8 (UDP) − 4 (ENet hdr) − 8 (SendUnreliable) = 1220 B
```

So `L = 1200 B` leaves 20 B spare on the strictest path. It also sits 164 B under ENet's 1364 B
fragmentation threshold (§1.2). Our code uses exactly this: `MAX_UNRELIABLE_PAYLOAD = 1200`
(`rust/protocol/src/lib.rs`) and `max_snapshot_bytes: 1200` (`rust/server/src/config.rs`).

---

## 3. Upstream vs downstream asymmetry

A client sends **its own** input. It receives **everyone visible**. With input rate `f_in` and
input size `I`:

```
up per client      U = f_in × (I + H_d)                    — O(1) in N
down per client    D = f × (Σ snapshot payload + d·H_d)     — O(k)
server ingress       = N × U                               — O(N)
server egress        = N × D                               — O(N·k)
```

Example for our `PlayerInput`. It is `1 type + 1 seq + 2 flags + 2 aim + 4 pos + 4 vel + 4 cursor
+ 2 render_tick + 2 rtt = 22 B` (`rust/protocol/src/client.rs` L154–164), sent once per
`SERVER_TICK_INTERVAL` (`client/scripts/network/prediction.gd` L83):

```
U(30 Hz) = 30 × (22 + 38) = 1 800 B/s = 14.4 kbit/s
U(60 Hz) = 60 × (22 + 38) = 3 600 B/s = 28.8 kbit/s
1000 clients' ingress at 30 Hz = 1000 × 14.4 kbit/s = 14.4 Mbit/s
```

Downstream per client is 10–270× larger than that in the §9 tables. The server's uplink is the
bottleneck. Client uplinks are not.

Valve exposes the same split with separate knobs. `cl_cmdrate` is the input packet rate ("usually
30") and `cl_updaterate` (default 20) is the Snapshot rate. The `rate` setting (bytes/s) caps
downstream per client [Valve, Source Multiplayer Networking].

---

## 4. Snapshot size and downstream bytes per second

### 4.1 The core formula

```
records per datagram   r = floor( (L − H_s) × 8 / b_e )
datagrams per Snapshot d = ceil( k / r )
Snapshot payload       P = d·H_s + ceil(k · b_e / 8)        (≈; each datagram rounds to a byte)
wire bytes / Snapshot  W = P + d·H_d
down per client        D = f × W
server egress          E = N × D = N · f · ( k·b_e/8 + d·(H_s + H_d) )
```

Drop the per-datagram terms and the headline is **bytes/s ≈ k × bytes_per_entity × f**. The
`d·(H_s+H_d)` term matters when `k·b_e` is small.

Our constants (`rust/protocol/src/snapshot.rs`):

- **Snapshot header** `H_s` = 1 type + 4 `server_tick` + 4 `server_ms` + 1 flags + 2 count =
  **12 B** for a full Snapshot, **16 B** for a delta (adds the 4 B `baseline_tick`).
- **Typed id**: 2-bit kind + 10 bits (player) / 15 (projectile) / 14 (monster, world effect)
  (`write_typed_id`, `wire_bits`).
- **Full player record**: 12 id + 3 animation + 16 flags + 2×16 position = **63 bits**.
- **Delta player record, position only**: 12 id + 5 mask + 32 position = **49 bits**.
- `r` (records per 1200 B datagram) = floor(1188×8/63) = **150** full player records, or
  floor(1184×8/49) = **193** position-delta records.

### 4.2 Reference points from the literature

- Fiedler, *Snapshot Compression*: 901 cubes at **321 bits** each, 60 Hz, ~32 B packet header.
  901 × 321 = 289 221 b, plus 256 b header = 289 477 b, × 60 = **17.37 Mbit/s**. That matches the
  article's "17.37 megabits per-second". After quantization the cube is **80 bits**
  (1 at-rest + 50 position + 29 orientation), against a target of **256 kbit/s**
  [Gaffer, Snapshot Compression].
- Fiedler, *Snapshot Interpolation*: 900 cubes at "225 bits or 28.1 bytes" each, plus 28 B IP/UDP
  header, × 60 Hz = 1 520 550 B/s (the article's "11.6 megabit/sec", ≈12.2 Mbit/s decimal). At
  10 Hz it is about 2 Mbit/s [Gaffer, Snapshot Interpolation].
- Tribes (1998): a 28.8k-modem client "could set a rate of 10 packets per second with a size of
  200 to produce about 2K of data per second". The game supported "up to 128 human or AI
  controlled players" [Tribes].
- Source: "players with a modem connection can't receive more than 5 to 7 KB/sec"
  [Valve, Source Multiplayer Networking].

---

## 5. Total egress: O(N²) naive broadcast vs O(N·k) with AoI

**Naive broadcast.** Every client sees every player, so `k = N − 1`:

```
E_naive = N · f · (N−1) · b_e/8  +  per-datagram terms   ⇒  Θ(N²)
```

Doubling players quadruples egress. Going from 64 to 1000 players (15.6×) multiplies
`N(N−1)` by 999 000 / 4 032 = **247.8×**.

**Area of Interest (AoI).** Each client only receives entities within radius `R`. With uniform
density `ρ = N / A` over area `A`:

```
k ≈ min( N − 1,  ρ·πR² )      and with a hard cap k_max:   k = min(N−1, ρπR², k_max)
E_AoI = N · f · k · b_e/8     ⇒  Θ(N·k), linear in N once k saturates
```

The saving factor is `(N−1)/k`. Tribes did this as "scope": the ghost manager "does not ghost all
objects in the simulation", and scoping is "performed using a spatial database". In-scope objects
are ordered by a priority computed from distance, projected size, relative velocity and interest
[Tribes §Ghost Manager, §Simulation Layer]. Fiedler's *State Synchronization* uses a **priority
accumulator**: add each object's priority every frame, send the top entries that fit the packet,
and reset the sent ones to zero [Gaffer, State Synchronization]. Our server does the same thing
with an AoI grid and hysteresis (`aoi_radius: 1000`, `aoi_exit_radius: 1100`,
`rust/server/src/config.rs`) and a per-peer byte budget capped at 1200 B
(`docs/netcode/performance-budgets.md`).

**Caveat: AoI is not magic.** If all N players crowd into one radius (a town square, a boss
fight), `ρπR² → N` and you are back at Θ(N²). The only thing that bounds that case is the hard
cap `k_max` (a byte budget plus priority). Plan capacity for the crowded case.

---

## 6. Quantization: bits per float at a given precision

A value in `[min, max]` sent with step `q` has `n = floor((max − min)/q) + 1` distinct values. It
needs:

```
bits = ceil( log2( (max − min)/q + 1 ) )
```

This is Fiedler's `bits_required(0, ceil((max−min)/res))` in `serialize_compressed_float`
[Gaffer, Serialization Strategies]. It reproduces his figures: x/y positions in [−256, 255] m at
512 values per metre come out at **18 bits** each, and z in [0, 32] m at **14 bits**
[Gaffer, Snapshot Compression].

| Quantity | Range | Step | Bits (formula) | vs f32 (32 b) |
|---|---|---|---|---|
| Arena coordinate | 2000 u (±1000) | 0.1 u | ceil(log2 20 001) = **15** | 2.1× smaller |
| Sanctuary x | 6656 u (±3328) | 0.1 u | ceil(log2 66 561) = **17** | 1.9× |
| Arena coordinate | 2000 u | 0.01 u | **18** | 1.8× |
| Arena coordinate | 2000 u | 1 u | **11** | 2.9× |
| Angle | 2π rad | 0.01 rad | ceil(log2 629.3) = **10** | 3.2× |

Rule of thumb: each 10× improvement in precision costs about log2(10) ≈ **3.3 bits** per component.

Ours: coordinates are `×10`, truncated toward zero, and clamped into an **i16** (16 bits, ±3276.7 u)
(`rust/protocol/src/quant.rs`). That is one bit over the 15-bit minimum for the Arena. Bit-packing
the arena exactly (15 + 15) would save 2 bits per position, about 3 % of a 63-bit record.

> **Side observation (verify):** `SANCTUARY_MAP_MIN/MAX` are ±3328 on x
> (`rust/sim_core/src/constants.rs` L93–94). The i16 wire coordinate saturates at ±3276.7, so an
> entity standing at |x| > 3276.7 would replicate clamped. The Sanctuary needs 17 bits per x at
> 0.1 u, or a coarser step.

Quake 3 does it differently. Each `netField_t` declares a bit width, where 0 means float. A float
that is a whole number in range goes out in `FLOAT_INT_BITS` (13) bits, otherwise in "all 32 bits"
[Q3 msg.c].

---

## 7. Delta compression vs full snapshots

**Mechanism.** The server encodes Snapshot `t` relative to the last Snapshot the client
**acknowledged**. Unchanged entities or fields are skipped or flagged with one bit:

- Source: "the server doesn't send a full world snapshot each time, but rather only changes (a
  delta snapshot) that happened since the last acknowledged update". Full snapshots are sent
  "only … when a game starts or a client suffers from heavy packet loss for a couple of seconds"
  [Valve].
- Quake 3: `PACKET_BACKUP 32`, a history of 32 old messages "for delta compression and ping
  estimation" [Q3 qcommon.h]. Each field is preceded by one changed bit, and a count of changed
  fields (`lc`) is written first [Q3 msg.c].
- Tribes: per-object **State Masks**, so only dirty state groups are re-sent
  ("partial object state updates") [Tribes].

**Savings formula.** Let `p` be the fraction of in-view entities that changed since the baseline,
`b_full` the full record size, `b_chg` the size of a changed delta record, and `b_unchg` the size of
an unchanged one (0 if omitted, a few bits if flagged):

```
b_delta = p·b_chg + (1−p)·b_unchg            savings = 1 − b_delta / b_full
```

| Scenario | p | b_full | b_delta (ours) | Saving |
|---|---|---|---|---|
| Bullet-hell: everyone moving | 1.0 | 63 b | 49 b (position-only delta) | **22 %** |
| Half the view idle, idle omitted | 0.5 | 63 b | 0.5 × 49 = 24.5 b | 61 % |
| Mostly static world (Fiedler's resting cubes) | low | 80 b | small | Fiedler estimates delta compression gives "another order of magnitude improvement" [Gaffer, State Synchronization] |

**For a fast shooter, delta compression buys far less than AoI.** When nearly everything moves
every Tick, you still send every position each Snapshot. Delta compression pays off on slow-changing
fields (flags, animation, HP) and on idle entities. The cost is extra state: per-client baselines and
a history ring (Sanglard measured the Q3 history at "8 MB for 4 players" [Sanglard, Q3 network]).

---

## 8. Snapshot interpolation vs deterministic lockstep

| | Snapshot interpolation (ours, Source, Q3) | Deterministic lockstep |
|---|---|---|
| Sent | world state (positions…) | inputs only |
| Bandwidth scales with | visible entities `k` | players `N` (each peer needs all inputs) |
| Needs determinism | no | yes ("difficult to implement … most physics simulations are not deterministic") [Gaffer, Deterministic Lockstep] |
| Added latency | interpolation buffer: Source 100 ms (`cl_interp 0.1`) at 20 Hz [Valve]; Fiedler's rule of thumb is ≈3× the send interval (300 ms at 10 Hz, 150 ms at 30 Hz, 85 ms at 60 Hz) [Gaffer, Snapshot Interpolation] | must wait for every input: "If it doesn't have the input, it has to wait" [Gaffer, Deterministic Lockstep] |
| Player-count sweet spot | many | Fiedler: "deterministic lockstep for 2-4 players at most" [Gaffer, Snapshot Interpolation] |

Lockstep's selling point is that "bandwidth is proportional to the size of the input, not the
number of objects" [Gaffer, Deterministic Lockstep]. It fits RTS-style unit counts, not hundreds
of players: each client needs all `N` inputs per step (`N·I·f` down), and one slow peer stalls
everyone. At MMO scale the choice is server-authoritative snapshots with AoI.

---

## 9. Worked examples: 64 vs 100 vs 1000 players at 30 Hz and 60 Hz

**Assumptions** (all stated; change them and re-run the formulas):

- IPv4, `H_d = 38 B` (§1.3); `L = 1200 B` (§2); `H_s = 12 B` full / 16 B delta (§4.1).
- Only player entities counted (projectiles and monsters add on top, same formula, different `b_e`).
- Each oversized Snapshot is split into ≤1200 B datagrams, each carrying its own `H_s`. (Our server
  actually refuses to split: it caps at 1200 B per peer and prioritizes. These tables show what
  naive replication would *demand*.)
- "AoI-64" means `k = min(N−1, 64)`.
- Three encodings: **naive 16 B/entity** (u16 id + 3 × f32 + u16 state = 128 b, unpacked);
  **ours full** (63 b); **ours delta, position-only** (49 b).

### 9.1 One case step by step: N = 1000, f = 30 Hz, naive broadcast, ours-full (63 b)

```
k = N − 1                                   = 999
r = floor((1200 − 12) × 8 / 63)             = floor(9504 / 63) = 150 records/datagram
d = ceil(999 / 150)                         = 7 datagrams per Snapshot
payload: 6 full datagrams of 150 records    = 6 × (12 + ceil(150×63/8)=1182) = 6 × 1194 = 7164 B
         + last datagram of 99 records      = 12 + ceil(99×63/8)=780       =  792 B
P                                           = 7 956 B
W = P + d × 38                              = 7 956 + 266 = 8 222 B per Snapshot
D = 30 × 8 222                              = 246 660 B/s ≈ 246.7 kB/s ≈ 1.97 Mbit/s per client
E = 1000 × D                                = 246.7 MB/s ≈ 1 973 Mbit/s ≈ 2.0 Gbit/s server egress
packets/s = N × d × f = 1000 × 7 × 30       = 210 000 datagrams/s
```

The same thing with AoI-64:

```
k = 64, d = 1, P = 12 + ceil(64×63/8)=504  = 516 B;  W = 516 + 38 = 554 B
D = 30 × 554 = 16 620 B/s ≈ 133 kbit/s;  E = 1000 × D ≈ 133 Mbit/s;  30 000 datagrams/s
```

Naive / AoI egress ratio = 1973 / 133 ≈ **14.8×**. The asymptotic factor (N−1)/k = 999/64 = 15.6×.
The difference comes from per-datagram overhead.

### 9.2 Full table: ours-full, 63 bits per player

| N | f | mode | k | d | W (B/Snapshot) | per client | server egress | datagrams/s |
|---|---|---|---|---|---|---|---|---|
| 64 | 30 | naive (=AoI-64) | 63 | 1 | 547 | 16.4 kB/s · 0.13 Mbit/s | **8.4 Mbit/s** | 1 920 |
| 64 | 60 | naive (=AoI-64) | 63 | 1 | 547 | 32.8 kB/s · 0.26 Mbit/s | **16.8 Mbit/s** | 3 840 |
| 100 | 30 | naive | 99 | 1 | 830 | 24.9 kB/s · 0.20 Mbit/s | **19.9 Mbit/s** | 3 000 |
| 100 | 30 | AoI-64 | 64 | 1 | 554 | 16.6 kB/s · 0.13 Mbit/s | 13.3 Mbit/s | 3 000 |
| 100 | 60 | naive | 99 | 1 | 830 | 49.8 kB/s · 0.40 Mbit/s | **39.8 Mbit/s** | 6 000 |
| 100 | 60 | AoI-64 | 64 | 1 | 554 | 33.2 kB/s · 0.27 Mbit/s | 26.6 Mbit/s | 6 000 |
| 1000 | 30 | naive | 999 | 7 | 8 222 | 246.7 kB/s · 1.97 Mbit/s | **1 973 Mbit/s** | 210 000 |
| 1000 | 30 | AoI-64 | 64 | 1 | 554 | 16.6 kB/s · 0.13 Mbit/s | 133 Mbit/s | 30 000 |
| 1000 | 60 | naive | 999 | 7 | 8 222 | 493.3 kB/s · 3.95 Mbit/s | **3 947 Mbit/s** | 420 000 |
| 1000 | 60 | AoI-64 | 64 | 1 | 554 | 33.2 kB/s · 0.27 Mbit/s | 266 Mbit/s | 60 000 |

### 9.3 Same grid, other encodings (server egress, Mbit/s)

| N, f | naive 16 B: all / AoI-64 | ours full 63 b: all / AoI-64 | ours delta 49 b: all / AoI-64 |
|---|---|---|---|
| 64, 30 | 16.3 / 16.3 | 8.4 / 8.4 | 6.8 / 6.8 |
| 64, 60 | 32.5 / 32.5 | 16.8 / 16.8 | 13.5 / 13.5 |
| 100, 30 | 40.4 / 25.8 | 19.9 / 13.3 | 15.9 / 10.7 |
| 100, 60 | 80.8 / 51.6 | 39.8 / 26.6 | 31.7 / 21.4 |
| 1000, 30 | **4 004** / 258 | 1 973 / 133 | 1 548 / 107 |
| 1000, 60 | **8 008** / 516 | 3 947 / 266 | 3 095 / 214 |

How to read this:

- **Hz is linear.** 30 → 60 Hz doubles everything.
- **Bit-packing is a constant factor** of about 2× here (128 b → 63 b). Delta compression adds about
  1.25× when everyone moves.
- **AoI is the only lever that changes the exponent.** At 1000 players a naive broadcast needs 2–8 Gbit/s
  of egress, which is more than a single 1 Gbit/s port can carry. With AoI-64 the same Instance
  needs 0.1–0.5 Gbit/s.
- **Packets per second matter too.** Naive 1000 @ 60 Hz is 420k datagrams/s, which means syscall
  and kernel cost. ENet sends one datagram per peer per flush, so the floor is `N × f` datagrams/s.
- **Monthly transfer.** 1 Gbit/s sustained = 125 MB/s × 2 592 000 s ≈ **324 TB/month**. So
  133 Mbit/s ≈ 43 TB/month. Many VPS plans meter transfer in single-digit TB, so egress cost
  can bind before bandwidth does.

---

## 10. CPU cost per Tick

The Tick budget is `1/f_tick`: **33.3 ms at 30 Hz, 16.7 ms at 60 Hz**. Valve notes that "a higher
tickrate increases the simulation precision, but also requires more CPU power and available
bandwidth" [Valve].

```
C_tick ≈ C_sim(N, projectiles)                      — movement + collision/hit checks
       + N · C_aoi                                  — each client's visible-set query
       + Σ_i k_i · c_rec                            — serialise k records per recipient  ⇒ O(N·k)
       + N · d · c_send                             — ENet framing + one sendto() per datagram
```

**Serialisation × recipients.** Record writes per second = `N · k · f`:

| N | k | f | records / Tick | records / s |
|---|---|---|---|---|
| 64 | 63 | 30 | 4 032 | 120 960 |
| 100 | 99 | 30 | 9 900 | 297 000 |
| 1000 | 999 | 30 | **999 000** | 29 970 000 |
| 1000 | 64 | 30 | 64 000 | 1 920 000 |
| 1000 | 999 | 60 | 999 000 | 59 940 000 |
| 1000 | 64 | 60 | 64 000 | 3 840 000 |

`c_rec` is not a citable constant. It depends on the encoder, so measure it (e.g. a `criterion`
bench around `Snapshot::encode`). As an **illustration only**, at an assumed 50 ns per bit-packed
record, naive 1000 players costs 999 000 × 50 ns ≈ **50 ms per Tick**. That alone blows both the
30 Hz and 60 Hz budget on one thread. AoI-64 costs 64 000 × 50 ns ≈ 3.2 ms. Two standard
mitigations: encode each entity's record **once per Tick** and copy bits per recipient, which turns
the inner cost into a memcpy; and spread peers across threads, since serialisation is
embarrassingly parallel per recipient.

**Collision / hit checks.** With `P` live projectiles and `T` targets, naive pairwise is
`P·T` per Tick. A uniform grid with cell size `c` over area `A` checks about `P · 9 · (T·c²/A)`
(3×3 neighbourhood). Illustration: Arena 2000 × 2000 u, `c = 64` u gives 976.6 cells. With
T = 1500 that is 1.54 targets per cell, so ≈13.8 candidates per projectile:

```
naive: 3000 projectiles × 1500 targets = 4 500 000 pair tests/Tick  (×30 = 135 M/s)
grid : 3000 × 13.8                       ≈ 41 500 pair tests/Tick   (~108× fewer)
```

As with AoI, the grid only helps while targets stay spread out. Crowding drives the per-cell count
back up.

---

## 11. Formula sheet (copy into the article)

```
H_d (IPv4, ENet unreliable, no reliable/ack/checksum) = 20 + 8 + 2 + 8 = 38 B
H_d (IPv6, with sent_time)                           = 40 + 8 + 4 + 8 = 60 B
Max ENet payload inside IPv6 min MTU                 = 1280 − 60 = 1220 B   → use L = 1200 B
ENet fragmentation threshold (default MTU 1392)      = 1392 − 4 − 24 = 1364 B

bits(range, step)  = ceil(log2(range/step + 1))
r                  = floor((L − H_s)·8 / b_e)
d                  = ceil(k / r)
D (down/client)    = f · ( ceil(k·b_e/8) + d·(H_s + H_d) )
U (up/client)      = f_in · (I + H_d)
E (server egress)  = N · D
k_naive = N − 1 → E = Θ(N²);   k_AoI = min(N−1, ρπR², k_max) → E = Θ(N·k)
delta: b = p·b_changed + (1−p)·b_unchanged
CPU/Tick ≈ C_sim + N·C_aoi + N·k·c_rec + N·d·c_send   (budget 1000/f_tick ms)
```

---

## Sources

Primary specifications
- [RFC 768] J. Postel, *User Datagram Protocol*, 1980. https://www.rfc-editor.org/rfc/rfc768
- [RFC 791] *Internet Protocol*, 1981 (§2.3 576-octet rule; §3.1 IHL). https://www.rfc-editor.org/rfc/rfc791
- [RFC 894] C. Hornig, *A Standard for the Transmission of IP Datagrams over Ethernet Networks*, 1984. https://www.rfc-editor.org/rfc/rfc894
- [RFC 8200] S. Deering, R. Hinden, *Internet Protocol, Version 6 (IPv6) Specification*, 2017 (§3, §5, §8.3). https://www.rfc-editor.org/rfc/rfc8200
- [RFC 9000] J. Iyengar, M. Thomson, *QUIC*, 2021 (§14 Datagram Size). https://www.rfc-editor.org/rfc/rfc9000

ENet source
- [ENet protocol.h] lsalzman/enet, `include/enet/protocol.h` (MTU bounds, header/command structs, flags). https://github.com/lsalzman/enet/blob/master/include/enet/protocol.h
- [ENet enet.h] lsalzman/enet, `include/enet/enet.h` (`ENET_HOST_DEFAULT_MTU = 1392`, version 1.3.18). https://github.com/lsalzman/enet/blob/master/include/enet/enet.h
- [rusty_enet] `rusty_enet` 0.4.0 crate source (README version table; `src/consts.rs`; `src/c/protocol.rs` structs, header/flag logic; `src/c/peer.rs` fragmentation). https://crates.io/crates/rusty_enet/0.4.0 (read locally from `~/.cargo/registry/src/index.crates.io-*/rusty_enet-0.4.0/`)

Game networking, first-party
- [Gaffer, Snapshot Compression] G. Fiedler, 2015. https://gafferongames.com/post/snapshot_compression/
- [Gaffer, Snapshot Interpolation] G. Fiedler, 2014. https://gafferongames.com/post/snapshot_interpolation/
- [Gaffer, State Synchronization] G. Fiedler, 2015. https://gafferongames.com/post/state_synchronization/
- [Gaffer, Deterministic Lockstep] G. Fiedler, 2014. https://gafferongames.com/post/deterministic_lockstep/
- [Gaffer, Serialization Strategies] G. Fiedler, 2016. https://gafferongames.com/post/serialization_strategies/
- [Gaffer, Packet Fragmentation] G. Fiedler, *Packet Fragmentation and Reassembly*, 2016. https://gafferongames.com/post/packet_fragmentation_and_reassembly/
- [Valve] Valve Developer Community, *Source Multiplayer Networking* (read via web.archive.org snapshot, 2024; the live wiki is bot-gated). https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
- [Tribes] M. Frohnmayer, T. Gift, *The TRIBES Engine Networking Model, or How to Make the Internet Rock for Multi-player Games* (Dynamix; model "first implemented in Starsiege TRIBES … December '98", paper written during TRIBES II development). PDF copy: https://www.gamedevs.org/uploads/tribes-networking-model.pdf
- [Q3 qcommon.h / msg.c / net_chan.c] id Software, *Quake III Arena* GPL source. https://github.com/id-Software/Quake-III-Arena/tree/master/code/qcommon
- [Sanglard, Q3 network] F. Sanglard, *Quake 3 Source Code Review: Network Model*, 2012 (secondary writeup of the source above; used only for the memory figure). https://fabiensanglard.net/quake3/network.php

Repo files referenced
- `rust/protocol/src/lib.rs` (`MAX_UNRELIABLE_PAYLOAD`, channel plan), `rust/protocol/src/snapshot.rs`
  (header layout, `wire_bits`), `rust/protocol/src/quant.rs`, `rust/protocol/src/client.rs`
  (`PlayerInput`), `rust/server/src/config.rs` (tick 30, AoI radii, `max_snapshot_bytes`),
  `rust/sim_core/src/constants.rs` (map bounds), `client/scripts/network/prediction.gd`
  (`INPUT_SEND_INTERVAL`).
- Calculations reproduced with a throwaway Python script implementing §11 exactly.
