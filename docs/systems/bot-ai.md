# Bot AI (load-testing swarm)

**Status:** Retired (2026-06-11). The Python swarm this doc describes was removed with the
WebSocket protocol; the live harness is the Rust `omega-load-test` crate
([`rust/load_test/`](../../rust/load_test/README.md)), which ports the load behaviors
verbatim and the strategy AI in **simplified** form (no A* hunt/flank planner). This doc
remains as the spec of the full tactical AI for anyone completing that port; the cited
sources live in git history before the Rust port.

The **bots** are the Python load-testing swarm in `load_testing/bot_client.py` (removed; see git history),
driven by `bot_swarm.py`. Each bot is a headless WebSocket client that authenticates and plays
like a real player, so to everyone else in the arena a bot **is** a remote player. This is how we
push 500–1000 concurrent clients at one headless server. This is distinct from the in-game
**monster** AI ([`monsters-ai.md`](monsters-ai.md)), which is server-side GDScript.

> The bot re-implements just enough of the client to be a believable player: it dead-reckons its own
> position, then **resyncs to the server's authoritative position every tick** from `STATE_UPDATE`
> (`_send_strategy_input`), so the swarm never drifts from what the server simulates.

## Behaviors

Selected per scenario (`BEHAVIOR_*`, `bot_client.py:1024`):

| Behavior | What it does |
|---|---|
| `idle` | Heartbeats only — no input. |
| `default` | Random walk + ~20 % shooting. |
| `movement` | Random walk, no shooting. |
| `combat` | Random walk + constant shooting. |
| `clustered` | All bots converge on (0,0) — worst-case Area-of-Interest stress. |
| `strategy` | **The realistic gameplay bot** — targets monsters then players, with a tactical state machine. |

The simple behaviors move at base `PLAYER_SPEED` (200) only; **sprint, stamina, and dash apply to
the `strategy` bot**, which is the one that looks and plays like a human.

## Strategy state machine

`_get_strategy_decision` produces a `TacticalDecision(move, aim, shoot, sprint)` each tick and sets
`_strategy_state` (`bot_client.py:157`):

| State | Meaning |
|---|---|
| `hunt` | No target in range — path toward likely action. |
| `engage` | Has a target — strafe at preferred range and shoot. |
| `flank` | Circle a target to attack from the side. |
| `evade` | Threatened — back off / dodge. |
| `dead` | Awaiting respawn (sends a respawn request after ~3.2 s). |

All thresholds scale with a per-bot `difficulty` (0..1, `_clamp_difficulty`): higher difficulty
sprints, flanks, and dashes more aggressively.

## Movement, speed, sprint & dash

Movement constants **mirror** [`game_constants.gd`](../../client/scripts/data/game_constants.gd)
so dead-reckoning matches the server-authoritative movement state machine
([`players-movement-state-machine.md`](players-movement-state-machine.md)) — keep them in sync:

| Constant (bot) | Value | Mirrors |
|---|---|---|
| `PLAYER_SPEED` | 200 | base walk speed |
| `PLAYER_SPRINT_MULTIPLIER` / `PLAYER_SPRINT_SPEED` | 1.6 / 320 | sprint |
| `PLAYER_DASH_COOLDOWN` | 5.5 s | dash cooldown |
| `BOT_SPRINT_STAMINA_FLOOR` | 25 | bot-only: stop sprinting below this |

- **Sprint adheres to the stamina meter.** The bot reads its authoritative `stamina`/`mana` from the
  owner-only `ACTION_CONFIRM` trailing bytes (`_handle_single_message`), and only requests sprint
  while `stamina > BOT_SPRINT_STAMINA_FLOOR`. So a bot sprints in bursts, drains, drops to a walk,
  regenerates, and sprints again — instead of holding sprint forever (which the server gates anyway,
  but matching here keeps dead-reckoning honest). This is why bots no longer "move fast" constantly.
- **Dash** is edge-triggered: `_should_dash` fires `INPUT_FLAG_DASH` (bit 8) while moving, gated by a
  local cooldown estimate (`_dash_cooldown_until`, the server enforces the real 5.5 s) and a
  difficulty-scaled chance that doubles while evading/flanking. The server's movement state machine
  validates the dash exactly as it does for a human.

## Networking

- Input at **10 Hz** (`PLAYER_INPUT`, 17-byte payload incl. the u16 `input_flags` with the dash bit),
  heartbeats at 1 Hz, server poll at 50 Hz.
- Reads `STATE_UPDATE` (resync position + observe entities), `ACTION_CONFIRM` (resync stamina/mana),
  `PROJECTILE_FIRED` (learn bullet ownership), and reports monster-bullet hits via `LOCAL_HIT_REPORT`
  so bots take PvE damage like real players.

## The eight questions

- **Client (bot):** decides movement/aim/shoot/sprint/dash; dead-reckons position; reports its own
  monster-bullet hits. It is a *client*, so nothing it claims is authoritative.
- **Server:** authoritative for everything — position, the movement state machine (sprint/stamina/dash
  gating), damage, death. Treats a bot exactly like a human player.
- **Predicted:** the bot dead-reckons position and tracks stamina locally, but resyncs both from the
  server every tick/confirm, so prediction is throwaway.
- **Replicated:** the bot observes other entities from `STATE_UPDATE` to pick targets.
- **Persisted:** none (bots use throwaway/guest characters).
- **Validated:** sprint/stamina/dash-cooldown all gated server-side; bot hit reports are rate-limited
  and plausibility-checked (`_local_hit_is_plausible`).
- **Can fail:** a bot's local stamina estimate lags the server by up to one `ACTION_CONFIRM` (~100 ms);
  simple behaviors don't sprint/dash (intentional — pure load patterns).
- **Tested:** the swarm itself is the test harness; `test_bot_client.py` covers packet build/parse;
  regression assertions in `regression_assertions.py` check observation distances per scenario.

## See also

- [`players-movement-state-machine.md`](players-movement-state-machine.md) — the server model the bots drive
- [`monsters-ai.md`](monsters-ai.md) — the *other* AI (in-game monsters, not bots)
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — `PLAYER_INPUT` / `ACTION_CONFIRM` byte layouts the bot mirrors
