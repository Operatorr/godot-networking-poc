Below is a **95-monster biome roster** for Omega Realm:

- **19 biomes**
- **4 themed regular monsters per biome** = 76 enemies
- **1 world/zone boss per biome** = 19 bosses

I kept each entry schema-friendly with:

`id` · `display_name` · `faction` · `type` · `archetype` · `tier` · `level` · `ai_profile` · `signature_ability`

For now, any monster whose `ai_profile` is not implemented yet can temporarily run as `ranged_kiter`, while keeping the intended profile in the data for future use.

---

# Biome Tier to Level Guide

| Biome Tier | Suggested Regular Level Range | Suggested Boss Level |
| ---------: | ----------------------------: | -------------------: |
| **Tier 1** |                           1–8 |                   10 |
| **Tier 2** |                          9–18 |                   20 |
| **Tier 3** |                         20–30 |                   32 |
| **Tier 4** |                         31–40 |                   42 |
| **Tier 5** |                         41–50 |                   55 |
| **Tier 6** |                         51–65 |                   70 |
| **Tier 7** |                        66–85+ |                  90+ |

---

# Implemented Monster — Toxic Slime (Tier 1)

The **Toxic Slime** is the POC's live test enemy — currently the only fully implemented
hostile monster in the Rust server (alongside the stationary Target Dummy, which is a
practice prop and grants no XP). It is a Tier 1 ranged kiter that spits a slow toxic glob
and retreats to its preferred distance.

`id`: `toxic_slime` · `faction`: `grave_waste` · `type`: `poisonous_amorphous` ·
`archetype`: `ranged_grunt` · `tier`: `1` · `level`: `1` · `ai_profile`: `ranged_kiter` ·
`signature_ability`: `toxic_spit` — slow poison projectile.

| Stat              | Value     | Source (`rust/server/src/monster.rs` → `TOXIC_SLIME`)      |
| ----------------- | --------- | ---------------------------------------------------------- |
| `max_health`      | 50        |                                                            |
| `move_speed`      | 120       |                                                            |
| `hitbox_radius`   | 16        |                                                            |
| `detection_range` | 650       |                                                            |
| `attack_range`    | 200       |                                                            |
| `shoot_cooldown`  | 0.75 s    |                                                            |
| `projectile_speed`| 300       |                                                            |
| `xp_reward`       | **20**    | granted to every player within `XP_SHARE_RADIUS` (500 u) on death |

**Experience:** killing a Toxic Slime grants 20 XP (the Tier 1 baseline). Five slimes take
a fresh character from level 1 to level 2; thereafter the curve scales so a same-level
monster is ~10 kills per level, which makes farming low-tier slimes at a high level
intentionally slow. Higher-tier monsters set a proportionally larger `xp_reward`. See
[`PROGRESSION.md`](PROGRESSION.md) for the full curve and radius-sharing rules.

---

# Mainland Biomes

---

## 1. Beach — Tier 1

Low-level coastal zone. Salt, bone, shipwrecks, drowned pilgrims, carrion birds, and weak corruption washing ashore.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                               |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Saltbitten Crab** <br> `id`: `saltbitten_crab` <br> `faction`: `shoreline_scavengers` <br> `type`: `mutated_crustacean` <br> `archetype`: `melee_grunt` <br> `tier`: `1` · `level`: `1` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `pinch_snap` — short melee snap with a tiny sideways dodge                    |
| Regular | **Drowned Beachcomber** <br> `id`: `drowned_beachcomber` <br> `faction`: `drowned_dead` <br> `type`: `waterlogged_undead` <br> `archetype`: `ranged_grunt` <br> `tier`: `1` · `level`: `2` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `brine_spit` — slow salt projectile that lightly damages and teaches dodging |
| Regular | **Carrion Gull** <br> `id`: `carrion_gull` <br> `faction`: `hostile_fauna` <br> `type`: `diseased_bird` <br> `archetype`: `fast_ambusher` <br> `tier`: `1` · `level`: `3` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `bone_peck_dive` — quick dive attack after a shriek telegraph                               |
| Regular | **Driftwood Penitent** <br> `id`: `driftwood_penitent` <br> `faction`: `death_cult` <br> `type`: `shipwreck_cultist` <br> `archetype`: `melee_grunt` <br> `tier`: `1` · `level`: `5` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `splinter_flail` — short cone of wooden shards                                     |
| Boss    | **The Barnacled Mourner** <br> `id`: `barnacled_mourner` <br> `faction`: `drowned_dead` <br> `type`: `shoreline_zone_boss` <br> `archetype`: `boss` <br> `tier`: `1` · `level`: `10` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `undertow_lament` — fires slow crescent waves while summoning drowned beachcombers |

---

## 2. Forest / Meadows — Tier 1

Starter wilderness. Looks alive from a distance, but the grass drinks blood and the deer no longer flee.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                        |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Gravehare** <br> `id`: `gravehare` <br> `faction`: `hostile_fauna` <br> `type`: `corrupted_small_beast` <br> `archetype`: `fast_ambusher` <br> `tier`: `1` · `level`: `1` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `panic_lunge` — zigzag dash toward the player                                      |
| Regular | **Thornback Boarlet** <br> `id`: `thornback_boarlet` <br> `faction`: `hostile_fauna` <br> `type`: `thorn_mutated_beast` <br> `archetype`: `melee_grunt` <br> `tier`: `1` · `level`: `3` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `thorn_charge` — short line charge that leaves a tiny thorn patch        |
| Regular | **Meadow Rotling** <br> `id`: `meadow_rotling` <br> `faction`: `grave_waste` <br> `type`: `plant_zombie` <br> `archetype`: `swarm` <br> `tier`: `1` · `level`: `4` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `spore_pop` — weak death puff in a small radius                                                 |
| Regular | **Tallow-Eyed Poacher** <br> `id`: `tallow_eyed_poacher` <br> `faction`: `fallen_imperium` <br> `type`: `mad_hunter` <br> `archetype`: `ranged_grunt` <br> `tier`: `1` · `level`: `6` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `rustbolt` — basic ranged projectile with a slight aim lead                |
| Boss    | **The Root-Hung Stag** <br> `id`: `root_hung_stag` <br> `faction`: `eldritch_corruption` <br> `type`: `forest_zone_boss` <br> `archetype`: `boss` <br> `tier`: `1` · `level`: `10` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `antler_thorn_barrage` — fires spreading thorn volleys and summons gravehares |

---

## 3. Dark Forest / Deep Forest / Dense Forest — Tier 2

The deeper version of the starting woods. Visibility should feel worse. Enemies ambush, poison, split, and swarm.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                           |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Blackbark Creeper** <br> `id`: `blackbark_creeper` <br> `faction`: `deep_forest_court` <br> `type`: `corrupted_treekin` <br> `archetype`: `melee_grunt` <br> `tier`: `2` · `level`: `9` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `root_snare` — brief root line that slows movement                                        |
| Regular | **Moth-Eaten Witchling** <br> `id`: `moth_eaten_witchling` <br> `faction`: `death_cult` <br> `type`: `forest_caster` <br> `archetype`: `caster` <br> `tier`: `2` · `level`: `11` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `moth_curse` — small fan of violet moth projectiles                                                |
| Regular | **Hollow Antler Lurker** <br> `id`: `hollow_antler_lurker` <br> `faction`: `eldritch_corruption` <br> `type`: `stalking_beast` <br> `archetype`: `stealth` <br> `tier`: `2` · `level`: `14` <br> `ai_profile`: `stealth_stalker` <br> `signature_ability`: `vanish_pounce` — fades, reappears nearby, then lunges                               |
| Regular | **Sap-Blood Broodmother** <br> `id`: `sap_blood_broodmother` <br> `faction`: `deep_forest_court` <br> `type`: `spider_tree_hybrid` <br> `archetype`: `summoner` <br> `tier`: `2` · `level`: `17` <br> `ai_profile`: `summoner_ritualist` <br> `signature_ability`: `hatch_barklings` — summons small swarm adds                                 |
| Boss    | **The Lantern in the Woods** <br> `id`: `lantern_in_the_woods` <br> `faction`: `eldritch_corruption` <br> `type`: `deep_forest_zone_boss` <br> `archetype`: `boss` <br> `tier`: `2` · `level`: `20` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `false_safe_light` — creates glowing lantern zones that erupt into bullet rings |

---

## 4. Reef — Tier 3

Colorful but hostile. Coral, infected fish, drowned knights, toxic spines, and sharp movement patterns.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                           |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Razorfan Reefling** <br> `id`: `razorfan_reefling` <br> `faction`: `reef_corruption` <br> `type`: `mutated_reef_fish` <br> `archetype`: `fast_ambusher` <br> `tier`: `3` · `level`: `20` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `razor_dash` — quick diagonal dash leaving shard trails                |
| Regular | **Coral-Spined Drowned** <br> `id`: `coral_spined_drowned` <br> `faction`: `drowned_dead` <br> `type`: `coral_undead` <br> `archetype`: `ranged_grunt` <br> `tier`: `3` · `level`: `23` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `coral_spike` — medium-speed piercing coral projectile                      |
| Regular | **Anemone Mouth** <br> `id`: `anemone_mouth` <br> `faction`: `reef_corruption` <br> `type`: `stationary_predator` <br> `archetype`: `caster` <br> `tier`: `3` · `level`: `26` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `stinging_fan` — radial fan of poison needles                                         |
| Regular | **Pearl-Eyed Cult Diver** <br> `id`: `pearl_eyed_cult_diver` <br> `faction`: `death_cult` <br> `type`: `aquatic_cultist` <br> `archetype`: `burrower` <br> `tier`: `3` · `level`: `29` <br> `ai_profile`: `burrower_emerge` <br> `signature_ability`: `undertide_stab` — disappears below terrain/water and emerges with a stab |
| Boss    | **The Crowned Coral Maw** <br> `id`: `crowned_coral_maw` <br> `faction`: `reef_corruption` <br> `type`: `reef_zone_boss` <br> `archetype`: `boss` <br> `tier`: `3` · `level`: `32` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `living_reef_bloom` — grows coral turrets around the arena that fire in patterns |

---

## 5. Mountains — Tier 3

Rock, snow, bones, old watchtowers, broken shrines, and thin-air madness.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                         |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Slateback Ram** <br> `id`: `slateback_ram` <br> `faction`: `hostile_fauna` <br> `type`: `mountain_beast` <br> `archetype`: `fast_ambusher` <br> `tier`: `3` · `level`: `20` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `cliff_charge` — long straight charge with knockback                              |
| Regular | **Pilgrim of the Thin Air** <br> `id`: `pilgrim_thin_air` <br> `faction`: `death_cult` <br> `type`: `mountain_zealot` <br> `archetype`: `ranged_grunt` <br> `tier`: `3` · `level`: `23` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `prayer_stone` — throws slow arcing stone projectiles                     |
| Regular | **Avalanche Husk** <br> `id`: `avalanche_husk` <br> `faction`: `grave_waste` <br> `type`: `frozen_undead` <br> `archetype`: `tank` <br> `tier`: `3` · `level`: `27` <br> `ai_profile`: `tank_guardian` <br> `signature_ability`: `snow_crush` — short shockwave stomp                                                         |
| Regular | **Sky-Claw Harrier** <br> `id`: `sky_claw_harrier` <br> `faction`: `hostile_fauna` <br> `type`: `mountain_bird` <br> `archetype`: `fast_ambusher` <br> `tier`: `3` · `level`: `30` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `talon_swoop` — repeated dive passes                                         |
| Boss    | **The Broken Peak Hermit** <br> `id`: `broken_peak_hermit` <br> `faction`: `death_cult` <br> `type`: `mountain_zone_boss` <br> `archetype`: `boss` <br> `tier`: `3` · `level`: `32` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `mountain_sutra` — creates falling rock markers and spiral projectile prayers |

---

## 6. Ocean — Tier 4

Open water, abyssal pressure, drowned fleets, leviathan larvae, and long-range bullet patterns.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                 |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Abyssal Lamprey** <br> `id`: `abyssal_lamprey` <br> `faction`: `drowned_dead` <br> `type`: `abyss_parasite` <br> `archetype`: `swarm` <br> `tier`: `4` · `level`: `31` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `blood_lock` — attempts to attach, then drains if not killed                                       |
| Regular | **Drowned Cannonier** <br> `id`: `drowned_cannonier` <br> `faction`: `drowned_dead` <br> `type`: `shipwreck_artillery` <br> `archetype`: `ranged_grunt` <br> `tier`: `4` · `level`: `34` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `rust_cannonball` — slow heavy projectile with splash                            |
| Regular | **Pressure-Warped Sailor** <br> `id`: `pressure_warped_sailor` <br> `faction`: `eldritch_corruption` <br> `type`: `mutated_sailor` <br> `archetype`: `elite` <br> `tier`: `4` · `level`: `37` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `depth_burst` — radial water-pressure burst                                 |
| Regular | **Leviathan Larva** <br> `id`: `leviathan_larva` <br> `faction`: `voidborn` <br> `type`: `abyssal_cosmic_spawn` <br> `archetype`: `burrower` <br> `tier`: `4` · `level`: `40` <br> `ai_profile`: `burrower_emerge` <br> `signature_ability`: `black_wake` — dives and resurfaces under target with a dark wave                        |
| Boss    | **The Drowned Fleet Admiral** <br> `id`: `drowned_fleet_admiral` <br> `faction`: `drowned_dead` <br> `type`: `ocean_zone_boss` <br> `archetype`: `boss` <br> `tier`: `4` · `level`: `42` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `broadside_of_the_dead` — fires ship-cannon volleys from both sides of the arena |

---

## 7. Unholy / Infected Outside — Tier 4

The land is visibly losing. Flesh-growths, unclean angels, plague pilgrims, and corruption vents.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                         |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Infected Pilgrim** <br> `id`: `infected_pilgrim` <br> `faction`: `infected_host` <br> `type`: `plague_cultist` <br> `archetype`: `melee_grunt` <br> `tier`: `4` · `level`: `31` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `boil_burst` — bursts into small toxic shots when low health                    |
| Regular | **Tumor-Hound** <br> `id`: `tumor_hound` <br> `faction`: `infected_host` <br> `type`: `mutated_war_beast` <br> `archetype`: `fast_ambusher` <br> `tier`: `4` · `level`: `34` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `rupture_lunge` — dash that leaves infected residue                                |
| Regular | **Spore-Mass Apostle** <br> `id`: `spore_mass_apostle` <br> `faction`: `death_cult` <br> `type`: `infected_priest` <br> `archetype`: `support` <br> `tier`: `4` · `level`: `37` <br> `ai_profile`: `support_buffer` <br> `signature_ability`: `unclean_benediction` — buffs nearby infected enemies                           |
| Regular | **Grafted Horror** <br> `id`: `grafted_horror` <br> `faction`: `eldritch_corruption` <br> `type`: `flesh_construct` <br> `archetype`: `elite` <br> `tier`: `4` · `level`: `40` <br> `ai_profile`: `elite_mutator` <br> `signature_ability`: `limb_rearrange` — alternates between melee slam and projectile spit              |
| Boss    | **The Saint of Open Wounds** <br> `id`: `saint_open_wounds` <br> `faction`: `infected_host` <br> `type`: `infected_zone_boss` <br> `archetype`: `boss` <br> `tier`: `4` · `level`: `42` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `woundfield_miracle` — places bleeding zones that spawn infected pilgrims |

---

# Underworld Biomes

---

## 8. Rocks — Tier 3

First descent into the Underworld. Stone, pressure, blind things, mineral parasites, and fossilized sinners.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                   |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Blind Stonegnawer** <br> `id`: `blind_stonegnawer` <br> `faction`: `underworld_fauna` <br> `type`: `cave_vermin` <br> `archetype`: `swarm` <br> `tier`: `3` · `level`: `20` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `gnaw_pack` — deals more pressure when near other stonegnawers                  |
| Regular | **Fossilized Sinner** <br> `id`: `fossilized_sinner` <br> `faction`: `grave_waste` <br> `type`: `stone_undead` <br> `archetype`: `tank` <br> `tier`: `3` · `level`: `23` <br> `ai_profile`: `tank_guardian` <br> `signature_ability`: `fossil_guard` — briefly reduces frontal damage                                   |
| Regular | **Crystal-Spine Leech** <br> `id`: `crystal_spine_leech` <br> `faction`: `underworld_fauna` <br> `type`: `mineral_parasite` <br> `archetype`: `ranged_grunt` <br> `tier`: `3` · `level`: `26` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `crystal_needle` — fast thin projectile                       |
| Regular | **Cave-Mouth Idol** <br> `id`: `cave_mouth_idol` <br> `faction`: `death_cult` <br> `type`: `stone_relic` <br> `archetype`: `caster` <br> `tier`: `3` · `level`: `30` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `echo_prayer` — bouncing projectile pattern                                            |
| Boss    | **The Buried Judge** <br> `id`: `buried_judge` <br> `faction`: `purgatory_judges` <br> `type`: `rock_zone_boss` <br> `archetype`: `boss` <br> `tier`: `3` · `level`: `32` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `sentence_of_stone` — marks players, then drops stone pillars on marked positions |

---

## 9. Scorched Ground — Tier 4

Charred transition biome. Burned earth, ash storms, crawling embers, and failed sacrifices.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                  |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Coal-Skinned Crawlers** <br> `id`: `coal_skinned_crawler` <br> `faction`: `ashen_exiles` <br> `type`: `burned_vermin` <br> `archetype`: `swarm` <br> `tier`: `4` · `level`: `31` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `ember_pop` — weak death explosion                                        |
| Regular | **Cinder Penitent** <br> `id`: `cinder_penitent` <br> `faction`: `death_cult` <br> `type`: `burned_cultist` <br> `archetype`: `melee_grunt` <br> `tier`: `4` · `level`: `34` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `flaming_flail` — short burning arc                                           |
| Regular | **Ashstorm Zealot** <br> `id`: `ashstorm_zealot` <br> `faction`: `ashen_exiles` <br> `type`: `ash_warrior` <br> `archetype`: `fast_ambusher` <br> `tier`: `4` · `level`: `37` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `ash_dash` — dash that briefly obscures nearby ground                      |
| Regular | **Charred Bell-Keeper** <br> `id`: `charred_bell_keeper` <br> `faction`: `death_cult` <br> `type`: `burned_support_priest` <br> `archetype`: `support` <br> `tier`: `4` · `level`: `40` <br> `ai_profile`: `support_buffer` <br> `signature_ability`: `smoke_benediction` — grants nearby allies brief speed           |
| Boss    | **The Ashen Matron** <br> `id`: `ashen_matron` <br> `faction`: `ashen_exiles` <br> `type`: `scorched_ground_zone_boss` <br> `archetype`: `boss` <br> `tier`: `4` · `level`: `42` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `mother_of_cinders` — spawns ember crawlers and fires expanding ash rings |

---

## 10. Underworld Mountain — Tier 4

Jagged black peaks below the world. Obsidian, chains, volcanic bones, and execution platforms.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                   |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Obsidian Climber** <br> `id`: `obsidian_climber` <br> `faction`: `underworld_fauna` <br> `type`: `cliff_predator` <br> `archetype`: `fast_ambusher` <br> `tier`: `4` · `level`: `31` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `wall_pounce` — sudden leap from terrain edges                                     |
| Regular | **Chain-Dragged Miner** <br> `id`: `chain_dragged_miner` <br> `faction`: `fallen_imperium` <br> `type`: `enslaved_undead` <br> `archetype`: `melee_grunt` <br> `tier`: `4` · `level`: `34` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `chain_sweep` — wide melee sweep                                                 |
| Regular | **Basalt Heretic** <br> `id`: `basalt_heretic` <br> `faction`: `death_cult` <br> `type`: `stone_cult_caster` <br> `archetype`: `caster` <br> `tier`: `4` · `level`: `37` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `basalt_cross` — four-way projectile cross                                                         |
| Regular | **Execution Peak Warden** <br> `id`: `execution_peak_warden` <br> `faction`: `obsidian_legion` <br> `type`: `underworld_guard` <br> `archetype`: `elite` <br> `tier`: `4` · `level`: `40` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `black_axe_judgment` — slow overhead strike that sends a line shockwave           |
| Boss    | **The Chained Summit** <br> `id`: `chained_summit` <br> `faction`: `obsidian_legion` <br> `type`: `underworld_mountain_zone_boss` <br> `archetype`: `boss` <br> `tier`: `4` · `level`: `42` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `mountain_in_chains` — pulls players with chains, then causes rockfall barrages |

---

## 11. Lava — Tier 5

High-tier damage zone. Fire, magma, molten armor, living furnaces, and positional punishment.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                    |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Magma-Blood Imp** <br> `id`: `magma_blood_imp` <br> `faction`: `daemon_host` <br> `type`: `lesser_fire_daemon` <br> `archetype`: `fast_ambusher` <br> `tier`: `5` · `level`: `41` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `lava_skip` — hops toward player, leaving small fire pools                             |
| Regular | **Molten Armor Husk** <br> `id`: `molten_armor_husk` <br> `faction`: `fallen_imperium` <br> `type`: `lava_bound_undead` <br> `archetype`: `tank` <br> `tier`: `5` · `level`: `44` <br> `ai_profile`: `tank_guardian` <br> `signature_ability`: `molten_guard` — slow march while shedding fire droplets                                  |
| Regular | **Pyre-Tongue Oracle** <br> `id`: `pyre_tongue_oracle` <br> `faction`: `death_cult` <br> `type`: `fire_caster` <br> `archetype`: `caster` <br> `tier`: `5` · `level`: `47` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `lava_sermon` — alternating fire lines                                                            |
| Regular | **Furnace-Born Behemoth** <br> `id`: `furnace_born_behemoth` <br> `faction`: `obsidian_legion` <br> `type`: `magma_giant` <br> `archetype`: `elite` <br> `tier`: `5` · `level`: `50` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `furnace_slam` — slam plus delayed lava bursts                                          |
| Boss    | **The Molten King Below** <br> `id`: `molten_king_below` <br> `faction`: `obsidian_legion` <br> `type`: `lava_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `5` · `level`: `55` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `crown_of_lava` — rotating lava beams, falling fire, and summoned magma imps |

---

## 12. Purgatory — Tier 6

Judgment zone. Grey flame, broken courts, execution wheels, guilt mechanics, and oppressive elites.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                                          |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Guilt-Hook Bailiff** <br> `id`: `guilt_hook_bailiff` <br> `faction`: `purgatory_judges` <br> `type`: `judgment_guard` <br> `archetype`: `elite` <br> `tier`: `6` · `level`: `51` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `guilt_hook` — throws chain hook that pulls or slows                                                            |
| Regular | **Ashen Jury Swarm** <br> `id`: `ashen_jury_swarm` <br> `faction`: `purgatory_judges` <br> `type`: `condemned_spirit_swarm` <br> `archetype`: `swarm` <br> `tier`: `6` · `level`: `55` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `collective_verdict` — grows more aggressive in groups                                                        |
| Regular | **Wheel-Broken Saint** <br> `id`: `wheel_broken_saint` <br> `faction`: `death_cult` <br> `type`: `martyr_abomination` <br> `archetype`: `caster` <br> `tier`: `6` · `level`: `60` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `wheel_of_pain` — rotating projectile ring                                                                       |
| Regular | **Confession Eater** <br> `id`: `confession_eater` <br> `faction`: `eldritch_corruption` <br> `type`: `sin_predator` <br> `archetype`: `stealth` <br> `tier`: `6` · `level`: `65` <br> `ai_profile`: `stealth_stalker` <br> `signature_ability`: `unspoken_lunge` — vanishes, then attacks from behind                                                         |
| Boss    | **The Grey-Flame Magistrate** <br> `id`: `grey_flame_magistrate` <br> `faction`: `purgatory_judges` <br> `type`: `purgatory_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `6` · `level`: `70` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `final_verdict` — marks players with judgment seals that explode into cross patterns |

---

## 13. Hell — Tier 7

Maximum Underworld biome. Daemons, living sin, torture geometry, impossible fire, and leaderboard-endangering combat.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                       |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Claw of the Ninth Furnace** <br> `id`: `claw_ninth_furnace` <br> `faction`: `daemon_host` <br> `type`: `greater_daemon_beast` <br> `archetype`: `fast_ambusher` <br> `tier`: `7` · `level`: `66` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `ninefold_pounce` — chained pounces with burning trails                    |
| Regular | **Hellscript Torturer** <br> `id`: `hellscript_torturer` <br> `faction`: `daemon_host` <br> `type`: `daemon_caster` <br> `archetype`: `caster` <br> `tier`: `7` · `level`: `72` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `script_of_agony` — writes delayed explosive glyphs under players                               |
| Regular | **Pit Archon of Nails** <br> `id`: `pit_archon_nails` <br> `faction`: `daemon_host` <br> `type`: `hell_elite` <br> `archetype`: `elite` <br> `tier`: `7` · `level`: `78` <br> `ai_profile`: `elite_mutator` <br> `signature_ability`: `nailstorm_form` — alternates melee slams and nail barrages                                           |
| Regular | **Screaming Gate-Flesh** <br> `id`: `screaming_gate_flesh` <br> `faction`: `eldritch_corruption` <br> `type`: `living_portal` <br> `archetype`: `summoner` <br> `tier`: `7` · `level`: `84` <br> `ai_profile`: `summoner_ritualist` <br> `signature_ability`: `birth_from_doorway` — summons lesser daemons from flesh gates                |
| Boss    | **The Horned Psalm of Ruin** <br> `id`: `horned_psalm_ruin` <br> `faction`: `daemon_host` <br> `type`: `hell_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `7` · `level`: `95` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `psalm_of_total_burning` — multi-phase fire, nail, and daemon-summon bullet hell |

---

# The Creator’s Realm Biomes

---

## 14. Grass — Tier 4

A false paradise. Too clean, too bright, too artificial. Grass that cuts, flowers that judge, animals made from divine residue.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                             |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Perfect Meadowling** <br> `id`: `perfect_meadowling` <br> `faction`: `creator_realm_life` <br> `type`: `artificial_fauna` <br> `archetype`: `melee_grunt` <br> `tier`: `4` · `level`: `31` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `clean_bite` — fast, sterile melee bite                                  |
| Regular | **Glass-Petal Sprinter** <br> `id`: `glass_petal_sprinter` <br> `faction`: `creator_realm_life` <br> `type`: `bladed_flora` <br> `archetype`: `fast_ambusher` <br> `tier`: `4` · `level`: `34` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `petal_cut_dash` — dash that emits small blade petals                |
| Regular | **Choirbud Bloom** <br> `id`: `choirbud_bloom` <br> `faction`: `creator_realm_life` <br> `type`: `singing_flower` <br> `archetype`: `support` <br> `tier`: `4` · `level`: `37` <br> `ai_profile`: `support_buffer` <br> `signature_ability`: `harmonic_growth` — heals or buffs nearby Creator’s Realm enemies                    |
| Regular | **White-Horn Grazer** <br> `id`: `white_horn_grazer` <br> `faction`: `creator_realm_life` <br> `type`: `holy_beast` <br> `archetype`: `tank` <br> `tier`: `4` · `level`: `40` <br> `ai_profile`: `tank_guardian` <br> `signature_ability`: `purity_charge` — heavy charge with a bright projectile wake                           |
| Boss    | **The Lamb That Was Not Born** <br> `id`: `lamb_not_born` <br> `faction`: `creator_realm_life` <br> `type`: `grass_zone_boss` <br> `archetype`: `boss` <br> `tier`: `4` · `level`: `42` <br> `ai_profile`: `boss_pattern` <br> `signature_ability`: `pastoral_deletion` — “peaceful” light rings that become lethal after a delay |

---

## 15. Cloud — Tier 5

High altitude false-heaven. Soft visuals, brutal mechanics. Winged constructs, judgment mist, angelic ruins.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                               |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Cloudbone Wisp** <br> `id`: `cloudbone_wisp` <br> `faction`: `skyborne_constructs` <br> `type`: `cloud_spirit` <br> `archetype`: `ranged_grunt` <br> `tier`: `5` · `level`: `41` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `mist_bolt` — soft-looking white projectile that curves slightly                                     |
| Regular | **Wingless Cherubim** <br> `id`: `wingless_cherubim` <br> `faction`: `creator_constructs` <br> `type`: `failed_angel_construct` <br> `archetype`: `swarm` <br> `tier`: `5` · `level`: `44` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `broken_halo_swarm` — groups orbit target and fire tiny halo shards                            |
| Regular | **Nimbus Executioner** <br> `id`: `nimbus_executioner` <br> `faction`: `skyborne_constructs` <br> `type`: `cloud_guard` <br> `archetype`: `elite` <br> `tier`: `5` · `level`: `47` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `thunder_glaive` — delayed lightning line attack                                                     |
| Regular | **Vapor Scripture Monk** <br> `id`: `vapor_scripture_monk` <br> `faction`: `creator_constructs` <br> `type`: `cloud_caster` <br> `archetype`: `caster` <br> `tier`: `5` · `level`: `50` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `scripture_mist` — overlapping slow-moving fog bullets                                          |
| Boss    | **The Choir Above Breath** <br> `id`: `choir_above_breath` <br> `faction`: `skyborne_constructs` <br> `type`: `cloud_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `5` · `level`: `55` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `hymn_of_suffocation` — shrinking safe zones, mist bullets, and cherubim summons |

---

## 16. Platform — Tier 5

Floating architecture, moving arenas, edge pressure, geometric patrols, and construct soldiers.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                                                      |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Edge-Walker Drone** <br> `id`: `edge_walker_drone` <br> `faction`: `creator_constructs` <br> `type`: `platform_patrol_construct` <br> `archetype`: `melee_grunt` <br> `tier`: `5` · `level`: `41` <br> `ai_profile`: `melee_chaser` <br> `signature_ability`: `edge_shove` — short shove attack that threatens positioning                                               |
| Regular | **Axis Turret Cherub** <br> `id`: `axis_turret_cherub` <br> `faction`: `creator_constructs` <br> `type`: `floating_turret_construct` <br> `archetype`: `ranged_grunt` <br> `tier`: `5` · `level`: `44` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `axis_burst` — fires in cardinal directions                                                             |
| Regular | **Falling-Step Assassin** <br> `id`: `falling_step_assassin` <br> `faction`: `creator_constructs` <br> `type`: `platform_stalker` <br> `archetype`: `stealth` <br> `tier`: `5` · `level`: `47` <br> `ai_profile`: `stealth_stalker` <br> `signature_ability`: `blink_step` — teleports between platform markers                                                            |
| Regular | **Bridge-Lock Sentinel** <br> `id`: `bridge_lock_sentinel` <br> `faction`: `creator_constructs` <br> `type`: `platform_guardian` <br> `archetype`: `tank` <br> `tier`: `5` · `level`: `50` <br> `ai_profile`: `tank_guardian` <br> `signature_ability`: `lockdown_field` — creates temporary denial zones                                                                  |
| Boss    | **The Architect of Falling Paths** <br> `id`: `architect_falling_paths` <br> `faction`: `creator_constructs` <br> `type`: `platform_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `5` · `level`: `55` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `delete_the_bridge` — arena sections become unsafe while construct turrets fire patterns |

---

## 17. Construct — Tier 6

Creator machinery. Precision enemies, clockwork movement, angular bullets, repair units, and modular guardians.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                                            |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Prime Gearling** <br> `id`: `prime_gearling` <br> `faction`: `creator_constructs` <br> `type`: `small_machine_construct` <br> `archetype`: `swarm` <br> `tier`: `6` · `level`: `51` <br> `ai_profile`: `swarm_pack` <br> `signature_ability`: `gear_bite` — small contact attacker that groups aggressively                                                    |
| Regular | **Axiom Rifle-Frame** <br> `id`: `axiom_rifle_frame` <br> `faction`: `creator_constructs` <br> `type`: `ranged_machine_construct` <br> `archetype`: `ranged_grunt` <br> `tier`: `6` · `level`: `55` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `axiom_shot` — fast straight laser-like projectile                                               |
| Regular | **Repair Cantor** <br> `id`: `repair_cantor` <br> `faction`: `creator_constructs` <br> `type`: `support_machine_construct` <br> `archetype`: `support` <br> `tier`: `6` · `level`: `60` <br> `ai_profile`: `support_buffer` <br> `signature_ability`: `restore_protocol` — heals nearby constructs over time                                                     |
| Regular | **Modular Judgment Frame** <br> `id`: `modular_judgment_frame` <br> `faction`: `creator_constructs` <br> `type`: `elite_machine_construct` <br> `archetype`: `elite` <br> `tier`: `6` · `level`: `65` <br> `ai_profile`: `elite_mutator` <br> `signature_ability`: `module_swap` — switches between shield, cannon, and blade modes                              |
| Boss    | **The Maker’s Unfinished Hand** <br> `id`: `makers_unfinished_hand` <br> `faction`: `creator_constructs` <br> `type`: `construct_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `6` · `level`: `70` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `five_finger_protocol` — five attack lanes, each finger using a different pattern |

---

## 18. Void — Tier 7

Cosmic horror biome. Impossible shapes, gravitational attacks, sanity fractures, starless enemies, and distorted bullet paths.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                            |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Regular | **Null-Eyed Drifter** <br> `id`: `null_eyed_drifter` <br> `faction`: `voidborn` <br> `type`: `void_wanderer` <br> `archetype`: `ranged_grunt` <br> `tier`: `7` · `level`: `66` <br> `ai_profile`: `ranged_kiter` <br> `signature_ability`: `null_bolt` — dark projectile that briefly accelerates mid-flight                                     |
| Regular | **Starless Mawling** <br> `id`: `starless_mawling` <br> `faction`: `voidborn` <br> `type`: `cosmic_predator_spawn` <br> `archetype`: `fast_ambusher` <br> `tier`: `7` · `level`: `72` <br> `ai_profile`: `ambush_charger` <br> `signature_ability`: `gravity_lunge` — lunge with slight pull effect before impact                                |
| Regular | **Angle-Broken Witness** <br> `id`: `angle_broken_witness` <br> `faction`: `voidborn` <br> `type`: `non_euclidean_caster` <br> `archetype`: `caster` <br> `tier`: `7` · `level`: `78` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `wrong_angle_barrage` — projectiles fire at offset, unnatural angles                           |
| Regular | **Black Orbit Apostle** <br> `id`: `black_orbit_apostle` <br> `faction`: `omega_court` <br> `type`: `void_elite` <br> `archetype`: `elite` <br> `tier`: `7` · `level`: `84` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `orbiting_singularity` — rotating black orbs around the enemy                                            |
| Boss    | **The Star That Hates Shape** <br> `id`: `star_that_hates_shape` <br> `faction`: `voidborn` <br> `type`: `void_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `7` · `level`: `95` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `geometry_collapse` — arena-wide pattern where safe spaces change shape every phase |

---

## 19. Higher Construct — Tier 7

The most dangerous Creator’s Realm biome. Perfect machines, divine enforcement, reality-editing constructs, and endgame bosses.

| Role    | Enemy                                                                                                                                                                                                                                                                                                                                                                                  |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Regular | **Seraphic Execution Frame** <br> `id`: `seraphic_execution_frame` <br> `faction`: `higher_constructs` <br> `type`: `divine_execution_machine` <br> `archetype`: `elite` <br> `tier`: `7` · `level`: `66` <br> `ai_profile`: `elite_hybrid` <br> `signature_ability`: `execution_vector` — locks an attack line, then fires a lethal beam                                              |
| Regular | **Throne-Wheel Observer** <br> `id`: `throne_wheel_observer` <br> `faction`: `higher_constructs` <br> `type`: `angelic_machine_caster` <br> `archetype`: `caster` <br> `tier`: `7` · `level`: `72` <br> `ai_profile`: `caster_zoner` <br> `signature_ability`: `wheel_of_law` — rotating ring of bullets with rotating gaps                                                            |
| Regular | **Golden Nullifier** <br> `id`: `golden_nullifier` <br> `faction`: `higher_constructs` <br> `type`: `anti_magic_construct` <br> `archetype`: `support` <br> `tier`: `7` · `level`: `78` <br> `ai_profile`: `support_buffer` <br> `signature_ability`: `nullify_field` — creates a suppression aura around allies                                                                       |
| Regular | **Perfected Judgment Colossus** <br> `id`: `perfected_judgment_colossus` <br> `faction`: `higher_constructs` <br> `type`: `divine_war_machine` <br> `archetype`: `mini_boss` <br> `tier`: `7` · `level`: `85` <br> `ai_profile`: `mini_boss_pattern` <br> `signature_ability`: `perfected_smite` — slow but massive tracking beam plus radial shards                                   |
| Boss    | **The Creator’s Abandoned Eye** <br> `id`: `creators_abandoned_eye` <br> `faction`: `higher_constructs` <br> `type`: `higher_construct_world_boss` <br> `archetype`: `world_boss` <br> `tier`: `7` · `level`: `100` <br> `ai_profile`: `world_boss_pattern` <br> `signature_ability`: `observe_and_erase` — targets movement paths, then deletes predicted locations with divine beams |

---

# Recommended Faction Registry

These are the factions used above.

```json
[
  "shoreline_scavengers",
  "drowned_dead",
  "hostile_fauna",
  "death_cult",
  "grave_waste",
  "deep_forest_court",
  "reef_corruption",
  "fallen_imperium",
  "eldritch_corruption",
  "voidborn",
  "infected_host",
  "underworld_fauna",
  "ashen_exiles",
  "obsidian_legion",
  "daemon_host",
  "purgatory_judges",
  "creator_realm_life",
  "skyborne_constructs",
  "creator_constructs",
  "higher_constructs",
  "omega_court"
]
```

---

# Recommended Biome Registry

Use these as canonical biome IDs in your spawn tables.

```json
{
  "mainland": [
    "beach",
    "forest_meadows",
    "dark_forest",
    "reef",
    "mountains",
    "ocean",
    "unholy_infected_outside"
  ],
  "underworld": [
    "rocks",
    "scorched_ground",
    "underworld_mountain",
    "lava",
    "purgatory",
    "hell"
  ],
  "creators_realm": [
    "grass",
    "cloud",
    "platform",
    "construct",
    "void",
    "higher_construct"
  ]
}
```

---

# Compact JSON Example

Here is one regular monster and one biome boss in a form close to your `MonsterDefinition.from_dict()` format.

```json
{
  "id": "saltbitten_crab",
  "display_name": "Saltbitten Crab",
  "archetype": "melee_grunt",
  "faction": "shoreline_scavengers",
  "tier": 1,
  "ai_profile": "melee_chaser",
  "type": "mutated_crustacean",

  "stats": {
    "max_health": 45,
    "move_speed": 115,
    "hitbox_radius": 12
  },

  "perception": {
    "detection_range": 450,
    "lose_interest_range": 700,
    "retarget_interval": 1.2,
    "leash_range": 0
  },

  "combat": {
    "attack_range": 80,
    "flee_distance": 0,
    "preferred_distance": 35,
    "shoot_cooldown": 1.15,
    "attack_duration": 0.3,
    "projectile_speed": 180,
    "projectile_damage": 5
  },

  "movement": {
    "steering_randomness": 0.18,
    "avoidance_distance": 40
  },

  "abilities": [
    {
      "id": "pinch_snap",
      "type": "short_melee",
      "damage": 7,
      "cooldown": 1.4,
      "telegraph": "claws raise and click before snapping"
    }
  ],

  "appearance": {
    "core_color": "#5A3A2E",
    "glow_color": "#9EC7D8",
    "shell_color": "#241A16"
  },

  "loot": {
    "xp": 4,
    "table": "beach_common"
  },

  "spawn": {
    "weight": "common",
    "biomes": ["beach"]
  },

  "networking": {
    "server_authoritative": true,
    "replicated": [
      "position",
      "velocity",
      "state",
      "target_id",
      "health",
      "cooldown_state",
      "ability_state"
    ],
    "client_predicted": false
  }
}
```

```json
{
  "id": "creators_abandoned_eye",
  "display_name": "The Creator's Abandoned Eye",
  "archetype": "world_boss",
  "faction": "higher_constructs",
  "tier": 7,
  "ai_profile": "world_boss_pattern",
  "type": "higher_construct_world_boss",

  "stats": {
    "max_health": 30000,
    "move_speed": 70,
    "hitbox_radius": 52
  },

  "perception": {
    "detection_range": 1000,
    "lose_interest_range": 1600,
    "retarget_interval": 0.45,
    "leash_range": 2000
  },

  "combat": {
    "attack_range": 720,
    "flee_distance": 0,
    "preferred_distance": 520,
    "shoot_cooldown": 0.65,
    "attack_duration": 1.0,
    "projectile_speed": 620,
    "projectile_damage": 190
  },

  "movement": {
    "steering_randomness": 0.04,
    "avoidance_distance": 120
  },

  "abilities": [
    {
      "id": "observe_and_erase",
      "type": "prediction_beam",
      "damage": 230,
      "cooldown": 7.0,
      "telegraph": "golden eye tracks the player's path before divine beams erase predicted locations"
    }
  ],

  "appearance": {
    "core_color": "#F2E5B8",
    "glow_color": "#FFFFFF",
    "shell_color": "#B89A38"
  },

  "loot": {
    "xp": 12000,
    "table": "creators_abandoned_eye_world"
  },

  "spawn": {
    "weight": "world_boss",
    "biomes": ["higher_construct"]
  },

  "networking": {
    "server_authoritative": true,
    "replicated": [
      "position",
      "velocity",
      "state",
      "target_id",
      "health",
      "cooldown_state",
      "ability_state",
      "phase"
    ],
    "client_predicted": false
  }
}
```
