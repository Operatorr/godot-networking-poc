# Audio manager & procedural sound

**Status:** Implemented (verified 2026-06-03 against code)

> Audio is a **pure client concern**. The server is authoritative for *what happened*
> (a kill, a shot, a hit — each a [Game event](../CONTEXT.md) or an animation-state flip in a
> [Snapshot](../CONTEXT.md)); the client decides *what it sounds like*. The
> [Authoritative server](../CONTEXT.md) never opens an audio device.

## What it is

`AudioManager` is an autoload singleton (`project.godot:23` →
`res://autoload/audio_manager.tscn` → `audio_manager.gd`). It owns one music player and two
pools of SFX players, and a sound library that is **generated procedurally at runtime** — there
are no SFX asset files in the repo. SFX waveforms come from `ProceduralAudio`, a pure
`RefCounted` of math (`procedural_audio.gd:4`).

The two **music** tracks are the exception: `_generate_procedural_audio` calls
`ProceduralAudio.generate_music()` but then immediately **overwrites** both library entries with
preloaded WAV assets — the `MAIN_MENU_MUSIC` / `ARENA_GAMEPLAY_MUSIC` consts. So at runtime music
is asset-backed, not procedural. See [Inconsistencies](#inconsistencies-found).

## Server vs client

`_ready` detects run target with the standard probe and **returns early in server mode** before
creating any player, bus, or sound (`audio_manager.gd:67-74`). Every public play path also
re-guards on `is_server` (`play_music:187`, `stop_music:219`, `play_sfx:267`,
`is_music_playing:474`), so the headless server is a no-op even if a gameplay script that runs in
both modes calls it.

## Mixer & player pools (client only)

| Thing | Value | Evidence |
|---|---|---|
| Buses | `Master` → `Music`, `SFX` (created if missing, both route to Master) | `audio_manager.gd:7-9, 114-147` |
| Music players | 1 (`AudioStreamPlayer`, on `Master` bus) | `audio_manager.gd:80-82` |
| UI SFX pool | 8 players (`SFX` bus) | `UI_SFX_POOL_SIZE`, `:50, 85-89` |
| Combat SFX pool | 16 players (`SFX` bus) | `COMBAT_SFX_POOL_SIZE`, `:51, 92-96` |
| Categories | `MUSIC / SFX_UI / SFX_PLAYER / SFX_MONSTER / SFX_COMBAT` enum | `AudioCategory`, `:15-21` |

> Note: the `music_player` is assigned to the **`Master`** bus, not the `Music` bus
> (`audio_manager.gd:81`). The per-track volume is applied directly on the player in dB
> (`_get_music_track_volume_db`, `:254-263`), so the `Music` bus exists but does not gate music
> level; `set_music_volume` adjusts the player, not the bus (`:409-416`). The `SFX` bus *does*
> gate all SFX (`set_sfx_volume` → `_set_bus_volume`, `:419-433`).

Voice stealing is naive: `_get_available_player` returns the first non-playing player in the
pool, or `pool[0]` (interrupting it) when all are busy (`audio_manager.gd:305-312`). At
500–1000-[player](../CONTEXT.md) scale this is fine because audio is gated by [AoI](../CONTEXT.md)
+ [Render delay](../CONTEXT.md) (you only hear entities you can see), not by player count.

## The sound library

Generated once in `AudioManager._generate_procedural_audio`. SFX from
`ProceduralAudio.generate_all_sounds` (incl. the `level_up` ding fired by `play_level_up`, and the
three **ability** cues — `mageblast` for the Mage, `go_invisible` for the Rogue's Shadowstep,
`charge` for the Warrior's Charge blast) plus 2 music tracks. Ability cues fire from `arena_base._handle_ability_effect_event` keyed on the
`ABILITY_EFFECT` `effect_id` (0 mageblast, 1 charge), and `go_invisible` fires on the local
player's STEALTH flag rising edge in `_sync_local_player_state`. The **looping** `charge_loop`
rumble plays *while* the Warrior is charging — `AudioManager.play_charge_loop()` /
`stop_charge_loop()` on a dedicated `AudioStreamPlayer`, driven by the predicted charge edges in
`prediction.gd._drive_charge_loop_sfx` (charge-specific, so the regular dash doesn't trigger it).

The full SFX library (generator + length per key):

| Key | Category | Generator | Length |
|---|---|---|---|
| `button_hover` / `button_click` | `sfx_ui` | `_gen_button_hover` / `_gen_button_click` | 15 / 35 ms |
| `player_shoot` | `sfx_player` | `_gen_player_shoot` | 70 ms |
| `player_hit` | `sfx_player` | `_gen_player_hit` | 60 ms |
| `player_death` | `sfx_player` | `_gen_player_death` | 350 ms |
| `player_kill` | `sfx_player` | `_gen_player_kill` | 180 ms |
| `level_up` | `sfx_player` | `_gen_level_up` (ascending C-major arpeggio) | 700 ms |
| `projectile_impact` | `sfx_player` | `_gen_projectile_impact` | 30 ms |
| `mageblast` / `go_invisible` / `charge` | `sfx_player` | `_gen_mageblast` / `_gen_go_invisible` / `_gen_charge` | 280 / 320 / 340 ms |
| `charge_loop` (looped) | `sfx_player` | `_gen_charge_loop` (LOOP_FORWARD) | 0.4 s loop |
| `footstep_l` / `footstep_r` | `sfx_player` | `_gen_footstep` | 20 ms |
| `monster_shoot` | `sfx_monster` | `_gen_monster_shoot` | 60 ms |
| `monster_hit` | `sfx_monster` | `_gen_monster_hit` | 50 ms |
| `monster_death` | `sfx_monster` | `_gen_monster_death` | 250 ms |
| `monster_spawn` | `sfx_monster` | `_gen_monster_spawn` | 150 ms |
| `menu_bgm` / `arena_ambience` | `music` | asset WAV (see above; `_gen_menu_bgm` / `_gen_arena_ambience` discarded) | 4 s / 8 s loop |

All synthesis is `static`, 22050 Hz, mono, 16-bit (`SAMPLE_RATE`/`MIX_RATE`, `:7-8`;
`_samples_to_wav`, `:50-73`) — sine/square/saw/filtered-noise oscillators (`:78-91`) shaped by an
ADSR envelope (`_envelope`, `:96-109`). No dependence on engine state, so generation is
deterministic and runs entirely on the client at startup.

## How gameplay triggers sound

Two consumers reach the singleton, both via a **lazy, cached** `_get_audio_manager()` that
fetches `root/AudioManager` once and re-fetches only if the cached node becomes invalid
(`client_entity_manager.gd:83-86`; `arena_base.gd:866-869`). This avoids a `get_node` per event
and survives scene reloads. Both call sites null-check before playing, so audio is best-effort and
never blocks gameplay.

Triggers are **server-confirmed only** — there is no [Prediction](../CONTEXT.md) of sound.
Combat audio rides on authoritative [Game events](../CONTEXT.md) and on remote
animation-state transitions decoded from [Snapshots](../CONTEXT.md):

| Sound | Trigger source | Evidence |
|---|---|---|
| Local shot | `PROJECTILE_FIRED` event whose `source_id` == local id (also `Player.gd shot_fired` signal) | `arena_base.gd:593-595, 637-651`, `:737-741` |
| Remote player shot | `PROJECTILE_FIRED`, source is a known remote player | `arena_base.gd:608-610` |
| Monster shot | `PROJECTILE_FIRED`, source ≥ `MONSTER_ENTITY_ID_START` and monster is spawned | `arena_base.gd:602-606` |
| Local death | `DAMAGE` event killing the local player | `arena_base.gd:558-568` |
| Local PvP kill | `KILL_PVP` event where killer == local id | `arena_base.gd:687-689` |
| Remote player hit / death | remote anim-state flips to `HIT` / `DEATH` in a Snapshot | `client_entity_manager.gd:367-372, 476-486` |
| Monster spawn | entity-spawned signal (PROJECTILE/MONSTER) | `client_entity_manager.gd:203-205` |
| Monster hit / death | `Monster.took_damage` / `died` signals | `client_entity_manager.gd:425-428, 444-452` |
| Projectile impact | `Projectile.hit` signal | `client_entity_manager.gd:499-502` |
| Footstep (L/R alternating) | local `Player.gd` movement | `player.gd:233-234`; `play_footstep:359-362` |
| UI hover / click | menu/login/character-creation button signals | `main_menu.gd:392-393`, `login_screen.gd:336-337`, `character_creation.gd:236-237` |
| Menu / arena music | `play_music("menu_bgm")` on menus; `play_music("arena_ambience")` on arena setup | `main_menu.gd:78`, `login_screen.gd:69`, `arena_base.gd:199-201` |

**Shoot audio is deliberately event-driven, not animation-driven.** `_play_remote_player_audio`
only handles `HIT`/`DEATH`, never shoot (`client_entity_manager.gd:476-486`), because a held
auto-fire animation would either miss repeated shots or double-play against the
`PROJECTILE_FIRED` event. The trade-off: because the client has **no shoot prediction**
(see [combat](combat-hits.md)), even the local shot sound waits for the server's
`PROJECTILE_FIRED` round-trip before it plays. There is no local muzzle SFX on key-press.

## Volume & settings

`AudioManager` listens to `GameManager.settings_changed` and applies master/music/SFX volumes
(`audio_manager.gd:102-106, 451-462`). `set_master_volume`/`set_sfx_volume` write the bus dB;
`set_music_volume` writes the music player dB directly (see mixer note). Per-track exported
multipliers `menu_bgm_volume` / `arena_bgm_volume` (default 0.2) scale music down further
(`:31-35, 254-263`). Linear→dB uses `linear_to_db`, flooring silence at `-80 dB` (`:432`).

## Inconsistencies found

- **Music is not procedural at runtime** despite the file/class naming. `generate_music()` is
  called and discarded; `audio_library["music"]` is replaced with preloaded asset WAVs
  (`MAIN_MENU_MUSIC` / `ARENA_GAMEPLAY_MUSIC` in `_generate_procedural_audio`). The two WAVs (`assets/audio/music/main_menu.wav`,
  `arena_gameplay.wav`) total ~68 MB and ship in the client export. The doc title says
  "procedural sound" — accurate for **SFX**, not music.
- **Music player is on the `Master` bus, not the `Music` bus** (`audio_manager.gd:81`), so the
  `Music` bus is created and routed but never carries the music signal; `set_music_volume` only
  moves the player, not the bus.
- `register_audio()` (`:465-470`) is a runtime-registration hook for asset streams but is unused
  by any gameplay path today.

## The eight questions

- **Client:** owns the entire audio system — bus setup, SFX synthesis, music playback, every trigger.
- **Server:** nothing; `AudioManager` returns early in headless mode and never allocates audio.
- **Predicted:** nothing — sound is never predicted; even the local shot waits for `PROJECTILE_FIRED`.
- **Replicated:** the *causes* are (Game events + Snapshot anim-state flips); the audio itself is local-only.
- **Persisted:** nothing — volume settings live in `GameManager.settings`, not in the audio system.
- **Validated:** nothing — audio cannot affect authoritative state; it is a read-only consumer.
- **Can fail:** voice stealing under a burst (16 combat slots) interrupts oldest SFX; a missed/stale anim flip can drop a hit/death cue; no failure touches gameplay.
- **Tested:** no automated audio test; verified manually in the arena. Headless server start asserts the early-return path (no audio device).

## See also

- [`combat-hits.md`](combat-hits.md) — `PROJECTILE_FIRED` / hit events that drive shoot & impact SFX
- [`players-movement.md`](players-movement.md) — local `Player.gd` footstep trigger
- [`monsters-ai.md`](monsters-ai.md) — monster spawn/hit/death audio sources
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — anim-state flips that cue remote hit/death sound
- [`../CONTEXT.md`](../CONTEXT.md) — Game event · Snapshot · AoI · Render delay
