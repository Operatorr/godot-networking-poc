## Fantasy Multiplayer Shooter - Godot 4.x / Rust

**Version:** 3.0 (Data-Driven Architecture)

**Date:** June 2026

**Project Type:** 3/4 Top-down 2D multiplayer bullet-hell shooter roguelite

**Architecture:** Hybrid Data-Driven with CMS Integration

---

## Data-Driven Architecture Overview

This specification uses a **hybrid data-driven architecture** where game content (enemies, items, spells, projectiles) is defined in JSON/database rather than individual scene files. This approach enables:

- **Live content updates** without rebuilding/patching the game
- **CMS integration** for designers to manage content without Godot access
- **Rapid iteration** on balance and new content
- **Reduced memory footprint** by sharing base scenes
- **Faster load times** compared to loading hundreds of individual scenes

What "data-driven" can and can't dodge

Free without recompiling (pure parameter changes):

- New enemy that's a reskin of an existing one with different HP/speed/damage
- New projectile spell defined by {damage, speed, radius, lifetime, pierce}
- Balance tuning, drop tables, spawn weights

Requires a recompile + deploy (genuinely new behavior):

- A boss that splits into 3 on death
- A spell that teleports you or reflects bullets
- Any new verb the simulation doesn't already understand

### Core Principle

```
90% data-driven (JSON definitions + base scenes)
+ 10% custom scenes (unique bosses/mechanics)
= Optimal flexibility and performance
```

---

## Table of Contents

1. Project Overview
2. Technology Stack
3. Project Folder Structure
4. Data-Driven Content System
5. Architecture Patterns
6. Service Layer
7. Repository Layer
8. Factory Layer
9. Scene Hierarchy
10. Core Systems & Classes
11. Design Patterns Reference
12. Network Architecture
13. Data Models
14. CMS Integration

---

## Project Overview

### Game Features

- **Genre:** Top-down 2D bullet-hell shooter
- **Style:** Fantasy with spells and character classes
- **Multiplayer:** Authoritative server architecture
- **Core Modes:**
  - PvE (Primary): Bullet-hell combat roguelite
    - After dying in Hardcore player are awarded Glory
    - Glory is used to spend on meta-progressions, You spend these to permanently boost your health, unlock new weapons, purchase passive buffs, or unlocking skilltree points, making subsequent runs more forgiving
    ```jsx
    award floor(lifetime XP / divisor)

    GloryXPDivisor = 100

    // GloryFor returns the Glory awarded when a character at (level, experience) dies
    // (hardcore) or is sacrificed (softcore): floor(TotalLifetimeXP / GloryXPDivisor).
    func GloryFor(level, experience int) int64 {
    	return TotalLifetimeXP(level, experience) / int64(GloryXPDivisor)
    }
    ```
  - PvP: Competitive arena battles
  - Tournament: Scheduled competitive events
  - Cutthroat Races: PoE-style leveling races with PvP enabled. (Every player starts a fresh reset (like Rust (Game)) at level 1 and simultaneously have to venture into the world and level up, while also fighting each other. PvPvE)
- **Progression:**
  - Fast leveling to max level cap (50)
    ```jsx
    # Exp Requirment
    MonsterEXP(level) = round(100 × 1.15^(level - 1))

    EXPRequired(level):
    Level 1 = 5 × MonsterEXP(1)
    Levels 2–49 = 10 × MonsterEXP(level)
    Level 50 = 0, because it is max level

    # Monster Exp
    MonsterEXP(monsterLevel) = round(100 × 1.15^(monsterLevel - 1))
    ```
  - Permadeath in hardcore mode, Softcore characters needs to voluntarily sacrifice their character in the Sanctum to gain Glory
  - Permanent stat potions for character power growth
  - Gear-focused endgame
- **Key Features:**
  - Multiple character races and classes
  - Permadeath mechanics
  - Persistent character progression
  - Competitive leaderboards

## Game World

### The Sanctuary

Game will have a Town (The Sanctuary, also called The Sanctum in the CMS) (Also called Hub Cities, shared instance)

- Town is multiplayer lobby with PvP turned off.
- In town players can access their banks
- Spend Glory to update their account
- Visit Vendors and talk to NPCs
- Buy and Sell equipment
- Trade and interact with other players
- Enter portals to go to the Arena, or enter the game World

### Open World

From the sanctuary the player can take three portals out to the open world levels / scenes / shards.

- Mainland
- Underworld
- Creators Realm

- Mainland (Tier 1 to 4)
  - Forest / Meadows (Tier 1)
  - Beach (Tier 1)
  - Dark Forest / Deep Forest / Dense Forest (Tier 2)
  - Reef (Tier 3)
  - Mountains (Tier 3)
  - Ocean (Tier 4)
  - Unholy / Infected (Outside) (Tier 4)
- Underworld (Tier 3 to 7)
  - Rocks (Tier 3)
  - Scorched Ground (Tier 4)
  - Mountain (Tier 4)
  - Lava (Tier 5)
  - Purgatory (Tier 6)
  - Hell (Tier 7)
- The Creators Realm (Tier 4 to 7)
  - Grass (Tier 4)
  - Cloud (Tier 5)
  - Platform (Tier 5)
  - Construct (Tier 6)
  - Void (Tier 7)
  - Higher Construct (Tier 7)

Mainland should be one shard, if we can make a large open world work, then all biomes in one scene or open world level, if we cant make that work then we need to break down each individual biome in its own shard and/or scene.

Underworld be another shard, and The Creators Ream be another shard.

One open world boss should exist in each biome.

### Dungeons

Each biome will have 1 Dungeon with a boss.

The dungeon should be procedurally generated so it has a unique layout every time.

### Loot Table (TBD)

We need a loot table, and each item needs a minimum Tier requirement to drop matching that it gets from the monster tier.

Some items also need biome requirement that says it can only drop in that biome.

Loot is for the most part equippable by all classes, but some class restriction exists.

Some items grans spells or abilities that the player can equip in their actionbar / ability slot.

### Classes

- Warrior
- Rogue
- Mage

(There are other classes in the game but they are deferred for later)

### HUD

I the HUD we have

- HP Bar
- Mana Bar (used for spells and abilities)
- Energy Bar (used for sprinting)
- EXP Bar

### Action-bar

- SPACE (Used for Dashing)
- RMB (Class unique ability)
- Slot 1
- Slot 2
- Slot 3
- Slot 4

Ability slots 1 through for are for equipping abilities received from Glory unlocks, items, or Skill-tree.

### Monsters

See docs/systems/MONSTERS.md

This doc should be moved to be under gdd folder, and references to it should be updated

### Bots

Bots are used for load testing.

We have created an AMAZING PvP bot AI that works super well and is very challenging.

This Bot AI should be preserved, and extracted into a design pattern where parts of it can be re-used into Monster AI, and tuned for difficulty.

### Difficulty

Difficulty in the game does not only come from Monster Level. It also comes from Monster AI, as some monsters can be high level but have very easy AI where the AI is tuned down, thus easy to defeat, whilst other monsters can be low level but have very highly tuned AI.

High tuned AI makes the monster move more to avoid your projectiles and aim better to hit you, and the latency in which it does this - reaction time.

---

## Technology Stack (NEEDS UPDATE)

### Client & Server

- **Engine:** Godot 4.x
- **Language:** GDScript
- **Rendering:** 2D sprite-based
- **Network:** Godot High-Level Multiplayer API (ENet)

### Backend Services

- **API Server:** FastAPI (Python) or Express (Node.js)
- **Database:** PostgreSQL
- **Cache:** Redis (for leaderboards, active sessions)
- **Authentication:** JWT tokens

### DevOps

- **Version Control:** Git
- **Container:** Docker (for server deployment)
- **Monitoring:** Prometheus + Grafana

---

## Project Folder Structure (NEEDS UPDATE)

And folder structure docs should be moved out into it’s own md file

```
res://
├── project.godot
├── export_presets.cfg
│
├── autoload/                          # Singleton systems (autoloaded)
│   ├── game_manager.gd               # Core game state coordination
│   ├── network_manager.gd            # Network connection handling
│   ├── auth_service.gd               # Authentication service
│   ├── event_bus.gd                  # Global event system
│   ├── audio_manager.gd              # Audio playback coordination
│   ├── settings_manager.gd           # Game settings persistence
│   └── tournament_manager.gd         # Tournament state management
│
├── scenes/                            # All scene files
│   ├── main.tscn                     # Entry point scene
│   │
│   ├── game/                         # Core gameplay scenes
│   │   ├── game_world.tscn          # Main game world container
│   │   ├── camera_controller.tscn   # Player camera system
│   │   └── game_hud.tscn            # In-game HUD overlay
│   │
│   ├── entities/                     # Base entity scenes (data-driven)
│   │   ├── player/
│   │   │   ├── player.tscn          # Player entity (loads race/class from data)
│   │   │   └── player_ghost.tscn    # Ghost mode after death
│   │   │
│   │   ├── enemies/
│   │   │   ├── base_enemy.tscn      # BASE: All standard enemies use this
│   │   │   ├── boss_base.tscn       # BASE: Boss enemies (if different mechanics)
│   │   │   └── special/             # Only truly unique bosses
│   │   │       ├── dragon_boss.tscn # Custom mechanics for special bosses
│   │   │       └── raid_boss.tscn
│   │   │
│   │   ├── projectiles/
│   │   │   └── base_projectile.tscn # BASE: All projectiles use this
│   │   │
│   │   ├── spells/
│   │   │   └── base_spell.tscn      # BASE: All spells use this
│   │   │
│   │   └── items/
│   │       ├── base_item.tscn       # BASE: Visual representation
│   │       └── pickup_item.tscn     # Ground item pickup
│   │
│   ├── levels/                       # Level/arena scenes
│   │   ├── base_level.tscn
│   │   ├── pve/
│   │   │   ├── dungeon_01.tscn
│   │   │   ├── dungeon_02.tscn
│   │   │   └── boss_arena.tscn
│   │   │
│   │   ├── pvp/
│   │   │   ├── arena_small.tscn # our current arena we have in game
│   │   │   ├── arena_medium.tscn
│   │   │   └── arena_large.tscn
│   │   │
│   │   └── race/ # We don't actually have any "race" scenes
│   │       ├── race_track_01.tscn # misinterpretation, not a race track
│   │       └── race_track_02.tscn # races are in instace of normal game world
│   │
│   └── ui/                           # User interface scenes
│       ├── menus/
│       │   ├── main_menu.tscn
│       │   ├── character_select.tscn
│       │   ├── character_creation.tscn
│       │   ├── lobby.tscn
│       │   └── settings_menu.tscn
│       │
│       ├── hud/
│       │   ├── health_bar.tscn
│       │   ├── mana_bar.tscn
│       │   ├── ability_bar.tscn
│       │   ├── minimap.tscn
│       │   └── damage_numbers.tscn
│       │
│       ├── inventory/
│       │   ├── inventory_panel.tscn
│       │   ├── equipment_panel.tscn
│       │   ├── item_slot.tscn
│       │   └── item_tooltip.tscn
│       │
│       └── tournament/
│           ├── tournament_list.tscn
│           ├── tournament_lobby.tscn
│           ├── leaderboard.tscn
│           └── race_timer.tscn
│
├── scripts/                          # GDScript files
│   ├── core/                        # Core game systems
│   │   ├── game_state.gd
│   │   ├── game_mode_base.gd
│   │   ├── game_mode_pve.gd
│   │   ├── game_mode_pvp.gd
│   │   └── game_mode_race.gd
│   │
│   ├── data/                        # Data loading and management (NEW)
│   │   ├── database_loader.gd      # Loads all JSON definitions
│   │   ├── content_updater.gd      # Downloads updated definitions from CDN/API
│   │   ├── definition_cache.gd     # Caches loaded definitions
│   │   │
│   │   ├── definitions/            # Definition classes
│   │   │   ├── enemy_definition.gd
│   │   │   ├── item_definition.gd
│   │   │   ├── spell_definition.gd
│   │   │   ├── projectile_definition.gd
│   │   │   ├── race_definition.gd
│   │   │   └── class_definition.gd
│   │   │
│   │   └── validators/             # Validate JSON schemas
│   │       ├── definition_validator.gd
│   │       └── schema_validator.gd
│   │
│   ├── factories/                   # Factory pattern for entity creation (NEW)
│   │   ├── enemy_factory.gd        # Creates enemies from definitions
│   │   ├── item_factory.gd         # Creates items from definitions
│   │   ├── spell_factory.gd        # Creates spells from definitions
│   │   ├── projectile_factory.gd   # Creates projectiles from definitions
│   │   └── entity_factory.gd       # Base factory
│   │
│   ├── entities/                    # Entity scripts
│   │   ├── base_entity.gd          # Abstract base for all entities
│   │   ├── living_entity.gd        # Entities with health/damage
│   │   │
│   │   ├── player/
│   │   │   ├── player_controller.gd
│   │   │   ├── player_input.gd
│   │   │   ├── player_movement.gd
│   │   │   ├── player_combat.gd
│   │   │   ├── player_stats.gd
│   │   │   ├── player_class_base.gd
│   │   │   ├── player_class_warrior.gd
│   │   │   ├── player_class_mage.gd
│   │   │   └── player_class_ranger.gd
│   │   │
│   │   ├── enemies/
│   │   │   ├── enemy_base.gd
│   │   │   ├── enemy_ai_base.gd
│   │   │   ├── enemy_ai_melee.gd
│   │   │   ├── enemy_ai_ranged.gd
│   │   │   └── enemy_spawner.gd
│   │   │
│   │   ├── projectiles/
│   │   │   ├── projectile_base.gd
│   │   │   └── projectile_pattern.gd  # Bullet hell patterns
│   │   │
│   │   └── spells/
│   │       ├── spell_base.gd
│   │       ├── spell_factory.gd
│   │       └── spell_effect.gd
│   │
│   ├── systems/                     # Game systems
│   │   ├── combat/
│   │   │   ├── damage_calculator.gd
│   │   │   ├── combat_system.gd
│   │   │   ├── hit_detection.gd
│   │   │   └── status_effect_manager.gd
│   │   │
│   │   ├── inventory/
│   │   │   ├── inventory_system.gd
│   │   │   ├── equipment_manager.gd
│   │   │   ├── item_generator.gd
│   │   │   └── loot_table.gd
│   │   │
│   │   ├── progression/
│   │   │   ├── experience_system.gd
│   │   │   ├── level_system.gd
│   │   │   ├── stat_system.gd
│   │   │   └── permanent_progression.gd
│   │   │
│   │   ├── persistence/
│   │   │   ├── save_system.gd
│   │   │   ├── character_repository.gd
│   │   │   └── permadeath_handler.gd
│   │   │
│   │   ├── tournament/
│   │   │   ├── tournament_system.gd
│   │   │   ├── tournament_bracket.gd
│   │   │   ├── race_tracker.gd
│   │   │   └── leaderboard_system.gd
│   │   │
│   │   └── spawning/
│   │       ├── spawn_system.gd
│   │       ├── wave_spawner.gd
│   │       └── object_pool.gd
│   │
│   ├── network/                     # Networking code
│   │   ├── network_client.gd
│   │   ├── network_server.gd
│   │   ├── network_sync.gd
│   │   ├── rpc_handlers.gd
│   │   ├── state_synchronizer.gd
│   │   └── interpolation.gd
│   │
│   ├── services/                    # Service layer
│   │   ├── auth_service.gd
│   │   ├── character_service.gd
│   │   ├── inventory_service.gd
│   │   ├── matchmaking_service.gd
│   │   ├── tournament_service.gd
│   │   └── api_client.gd
│   │
│   ├── repositories/                # Data access layer
│   │   ├── base_repository.gd
│   │   ├── character_repository.gd
│   │   ├── inventory_repository.gd
│   │   ├── tournament_repository.gd
│   │   └── cache_repository.gd
│   │
│   ├── ui/                          # UI controllers
│   │   ├── base_menu.gd
│   │   ├── main_menu_controller.gd
│   │   ├── character_select_controller.gd
│   │   ├── inventory_controller.gd
│   │   └── tournament_ui_controller.gd
│   │
│   └── utils/                       # Utility classes
│       ├── math_utils.gd
│       ├── timer_utils.gd
│       ├── vector_utils.gd
│       ├── object_pooler.gd
│       └── signal_bus.gd
│
├── resources/                       # Custom Resource definitions
│   ├── character/
│   │   ├── character_data.gd       # Character save data
│   │   ├── character_race.gd       # Race definitions
│   │   ├── character_class.gd      # Class definitions
│   │   └── character_stats.gd      # Stat definitions
│   │
│   ├── items/
│   │   ├── item_base.gd
│   │   ├── item_weapon.gd
│   │   ├── item_armor.gd
│   │   ├── item_consumable.gd
│   │   └── item_database.gd
│   │
│   ├── spells/
│   │   ├── spell_data.gd
│   │   ├── spell_database.gd
│   │   └── spell_effect_data.gd
│   │
│   ├── loot/
│   │   ├── loot_table.gd
│   │   └── loot_pool.gd
│   │
│   └── game_config/
│       ├── game_balance.gd
│       ├── difficulty_settings.gd
│       └── network_config.gd
│
├── assets/                          # All game assets
│   ├── sprites/
│   │   ├── characters/
│   │   ├── enemies/
│   │   ├── projectiles/
│   │   ├── effects/
│   │   ├── items/
│   │   └── ui/
│   │
│   ├── tilesets/
│   │   ├── dungeon_tileset.png
│   │   └── arena_tileset.png
│   │
│   ├── audio/
│   │   ├── music/
│   │   ├── sfx/
│   │   └── ambient/
│   │
│   ├── fonts/
│   │   └── main_font.ttf
│   │
│   └── shaders/
│       ├── hit_flash.gdshader
│       └── outline.gdshader
│
├── data/                            # JSON/CSV content definitions (NEW)
│   ├── enemies/
│   │   ├── enemy_database.json     # All enemy definitions
│   │   ├── boss_database.json      # Boss-specific definitions
│   │   ├── ai_behaviors.json       # AI behavior configurations
│   │   └── spawn_tables.json       # Enemy spawn tables by zone
│   │
│   ├── items/
│   │   ├── weapon_database.json    # All weapon definitions
│   │   ├── armor_database.json     # All armor definitions
│   │   ├── consumable_database.json
│   │   ├── affix_pool.json         # Random affix definitions
│   │   └── stat_potions.json       # Permanent stat potion types
│   │
│   ├── spells/
│   │   ├── spell_database.json     # All spell definitions
│   │   ├── spell_effects.json      # Visual/mechanical effects
│   │   └── class_abilities.json    # Class-specific ability sets
│   │
│   ├── projectiles/
│   │   ├── projectile_database.json # All projectile types
│   │   └── bullet_patterns.json    # Bullet hell pattern definitions
│   │
│   ├── characters/
│   │   ├── race_database.json      # Character race definitions
│   │   ├── class_database.json     # Character class definitions
│   │   └── starting_stats.json     # Starting stat templates
│   │
│   ├── loot/
│   │   ├── loot_tables.json        # Drop tables by enemy/zone
│   │   └── rarity_weights.json     # Rarity roll probabilities
│   │
│   ├── balance/
│   │   ├── damage_formulas.json    # Damage calculation configs
│   │   ├── level_scaling.json      # XP curves and scaling
│   │   └── stat_caps.json          # Maximum stat values
│   │
│   ├── tournaments/
│   │   ├── tournament_configs.json # Tournament rule sets
│   │   └── race_tracks.json        # Race configuration
│   │
│   └── schemas/                    # JSON schemas for validation
│       ├── enemy_schema.json
│       ├── item_schema.json
│       ├── spell_schema.json
│       └── projectile_schema.json
│
├── tests/                           # Unit tests
│   ├── unit/
│   ├── integration/
│   └── test_utils.gd
│
└── addons/                          # Third-party plugins
    └── gut/                         # Godot Unit Test framework
```

---

## Data-Driven Content System

### Philosophy

Instead of creating individual scene files for every enemy, item, spell, and projectile (which would result in thousands of scenes), this architecture uses:

- **Base Scenes:** Shared template scenes (e.g., `base_enemy.tscn`)
- **JSON Definitions:** Content data stored in JSON files
- **Factories:** Factory classes that instantiate base scenes and apply definitions
- **Hot Updates:** Content can be updated without rebuilding/patching the game

### Content Flow

```
JSON Definition → Factory → Base Scene → Configured Entity
     ↓              ↓           ↓              ↓
  "goblin"   EnemyFactory  base_enemy  Goblin Instance
  stats data    reads        .tscn      with goblin
                & applies              stats applied
```

### Example: Enemy System

### Traditional Approach (NOT USED)

```
scenes/enemies/
├── goblin.tscn          (50 KB)
├── orc.tscn             (50 KB)
├── fire_mage.tscn       (50 KB)
├── ice_wizard.tscn      (50 KB)
└── ... 100 more enemies (5 MB total)

To add new enemy: Create new scene → Rebuild game → Deploy patch
```

### Data-Driven Approach (USED)

```
scenes/enemies/
└── base_enemy.tscn      (50 KB)

data/enemies/
└── enemy_database.json  (100 KB for 100+ enemies)

To add new enemy: Add JSON entry → Upload to CDN → Game auto-updates
```

### Advantages

| Aspect        | Benefit                               |
| ------------- | ------------------------------------- |
| **Memory**    | 97% reduction (1 scene vs 100 scenes) |
| **Load Time** | 3x faster (load 1 scene + parse JSON) |
| **Iteration** | Update JSON, no rebuild needed        |
| **Balance**   | Live hotfix patches (KB not GB)       |
| **Designers** | Use CMS, no Godot knowledge needed    |
| **Modding**   | Easy to add custom content via JSON   |
| **Testing**   | A/B test different values easily      |

### What Can Be Data-Driven

✅ **Fully Data-Driven (90% of content):**

- Enemy stats (health, damage, speed, AI type)
- Item properties (damage, defense, affixes)
- Spell parameters (damage, cooldown, mana cost, range)
- Projectile behavior (speed, lifetime, pierce count)
- Loot tables and drop rates
- Character races and class stats
- Balance values and formulas

❌ **Requires Code (10% of content):**

- New AI behaviors (e.g., “teleport when low health”)
- New spell mechanics (e.g., first chain lightning implementation)
- New item affix types
- Complex boss mechanics with state machines
- Unique visual effects

### Hybrid Approach for Special Cases

For the 10% of content that needs unique mechanics:

```
# Special boss inherits from base but adds custom behavior# special/dragon_boss.tscnextends BaseEnemy
func _ready():
    super._ready()
    # Custom phase-based behaviorfunc _on_health_threshold(percent: float):
    if percent < 0.5:
        enter_rage_phase()
```

Still loads stats from database, but adds custom scripting for unique mechanics.

---

## Architecture Patterns

### Overall Architecture: Clean Architecture / Hexagonal Architecture

```
┌─────────────────────────────────────────────────┐
│              Presentation Layer                  │
│  (Scenes, UI Controllers, Input Handlers)       │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│              Application Layer                   │
│    (Services, Game Systems, Use Cases)          │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│               Domain Layer                       │
│  (Entities, Value Objects, Business Logic)      │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│            Infrastructure Layer                  │
│  (Repositories, Network, External APIs)         │
└─────────────────────────────────────────────────┘
```

### Key Principles

1. **Separation of Concerns:** Each system has a single responsibility
2. **Dependency Injection:** Pass dependencies through constructors/setters
3. **Interface Segregation:** Small, focused interfaces (using duck typing in GDScript)
4. **Composition Over Inheritance:** Use components and systems
5. **Event-Driven Architecture:** Loose coupling through event bus
6. **Server Authority:** Server validates all game-critical operations

---

## Service Layer

The service layer handles business logic and coordinates between systems. Services are stateless and injected where needed.

### Service Classes

### **AuthService** (`autoload/auth_service.gd`)

**Pattern:** Singleton

**Purpose:** Manages authentication and session management

### **CharacterService** (`scripts/services/character_service.gd`)

**Pattern:** Service Layer

**Purpose:** Character management business logic

### **InventoryService** (`scripts/services/inventory_service.gd`)

**Pattern:** Service Layer

**Purpose:** Inventory and equipment operations

### **MatchmakingService** (`scripts/services/matchmaking_service.gd`)

**Pattern:** Service Layer

**Purpose:** Matchmaking and lobby management

### **TournamentService** (`scripts/services/tournament_service.gd`)

**Pattern:** Service Layer

**Purpose:** Tournament and race management

### **APIClient** (`scripts/services/api_client.gd`)

**Pattern:** Facade

**Purpose:** HTTP requests to backend API

---

## Repository Layer

Repositories abstract data access. They handle persistence to local cache, remote database, or both.

### Repository Classes

### **BaseRepository** (`scripts/repositories/base_repository.gd`)

**Pattern:** Repository Pattern

**Purpose:** Abstract base for all repositories

### **CharacterRepository** (`scripts/repositories/character_repository.gd`)

**Pattern:** Repository Pattern

**Purpose:** Character data persistence

### **InventoryRepository** (`scripts/repositories/inventory_repository.gd`)

**Pattern:** Repository Pattern

**Purpose:** Inventory data persistence

### **TournamentRepository** (`scripts/repositories/tournament_repository.gd`)

**Pattern:** Repository Pattern

**Purpose:** Tournament and race data

### **CacheRepository** (`scripts/repositories/cache_repository.gd`)

**Pattern:** Repository Pattern + Cache Aside

**Purpose:** Local caching for performance

---

## Factory Layer

The factory layer creates game entities from JSON definitions. Factories are responsible for instantiating base scenes and applying configuration data.

### Factory Architecture

```
Definition (JSON) → Factory → Configured Entity
```

### Factory Classes

### **EntityFactory** (`scripts/factories/entity_factory.gd`)

**Pattern:** Abstract Factory

**Purpose:** Base class for all factories

### **EnemyFactory** (`scripts/factories/enemy_factory.gd`)

**Pattern:** Factory + Builder

**Purpose:** Create enemies from definitions

### **ItemFactory** (`scripts/factories/item_factory.gd`)

**Pattern:** Factory + Builder + Prototype

**Purpose:** Create items with procedural generation

### **SpellFactory** (`scripts/factories/spell_factory.gd`)

**Pattern:** Factory + Flyweight

**Purpose:** Create spell instances from definitions

### **ProjectileFactory** (`scripts/factories/projectile_factory.gd`)

**Pattern:** Factory + Object Pool

**Purpose:** Create projectiles (with pooling for performance)

### Factory Initialization

All factories should be initialized at game start:

---

## Scene Hierarchy

### Main Scene Tree

```
Main (Node)
└── GameManager (AutoLoad)

MainMenu (Control)
├── Background (TextureRect)
├── MenuButtons (VBoxContainer)
│   ├── PlayButton (Button)
│   ├── CharactersButton (Button)
│   ├── TournamentsButton (Button)
│   └── SettingsButton (Button)
└── VersionLabel (Label)

CharacterSelect (Control)
├── CharacterList (ItemList)
├── CharacterDetails (Panel)
│   ├── PortraitTexture (TextureRect)
│   ├── NameLabel (Label)
│   ├── ClassLabel (Label)
│   ├── LevelLabel (Label)
│   └── PlayButton (Button)
├── CreateCharacterButton (Button)
└── DeleteCharacterButton (Button)

GameWorld (Node2D)
├── CameraController (Camera2D)
├── LevelContainer (Node2D)
│   └── CurrentLevel (Node2D)
│       ├── TileMap (TileMap)
│       ├── SpawnPoints (Node2D)
│       └── NavigationRegion2D (NavigationRegion2D)
├── EntityContainer (Node2D)
│   ├── PlayersContainer (Node2D)
│   ├── EnemiesContainer (Node2D)
│   ├── ProjectilesContainer (Node2D)
│   └── ItemsContainer (Node2D)
└── UILayer (CanvasLayer)
    └── GameHUD (Control)

Player (CharacterBody2D)
├── Sprite2D (Sprite2D)
├── CollisionShape2D (CollisionShape2D)
├── PlayerController (Node)
├── PlayerInput (Node)
├── PlayerMovement (Node)
├── PlayerCombat (Node)
├── PlayerStats (Node)
├── HealthBar (Control)
└── NetworkSynchronizer (MultiplayerSynchronizer)

Enemy (CharacterBody2D)
├── Sprite2D (Sprite2D)
├── CollisionShape2D (CollisionShape2D)
├── EnemyAI (Node)
├── CombatComponent (Node)
├── StatsComponent (Node)
├── HealthBar (Control)
└── NetworkSynchronizer (MultiplayerSynchronizer)

Projectile (Area2D)
├── Sprite2D (Sprite2D)
├── CollisionShape2D (CollisionShape2D)
├── ProjectileMovement (Node)
├── ProjectileDamage (Node)
└── Lifetime (Timer)
```

---

## Core Systems & Classes

### 1. Autoload Singletons

### **GameManager** (`autoload/game_manager.gd`)

**Pattern:** Singleton + Facade

**Purpose:** Central coordinator for game state

### **NetworkManager** (`autoload/network_manager.gd`)

**Pattern:** Singleton + Facade

**Purpose:** Network connection and synchronization

### **EventBus** (`autoload/event_bus.gd`)

**Pattern:** Observer / Event Aggregator

**Purpose:** Global event broadcasting

### **AudioManager** (`autoload/audio_manager.gd`)

**Pattern:** Singleton + Object Pool

**Purpose:** Audio playback management

---

### 2. Entity System

### **BaseEntity** (`scripts/entities/base_entity.gd`)

**Pattern:** Template Method + Component

**Purpose:** Abstract base for all game entities

### **LivingEntity** (`scripts/entities/living_entity.gd`)

**Pattern:** Component-Based

**Purpose:** Entities with health, damage, and death

### **Player** (`scripts/entities/player/player_controller.gd`)

**Pattern:** Component-Based + State

**Purpose:** Player character controller

### **PlayerInput** (`scripts/entities/player/player_input.gd`)

**Pattern:** Command Pattern

**Purpose:** Input handling and command creation

### **PlayerMovement** (`scripts/entities/player/player_movement.gd`)

**Pattern:** Strategy

**Purpose:** Movement logic

### **PlayerCombat** (`scripts/entities/player/player_combat.gd`)

**Pattern:** Strategy + Command

**Purpose:** Combat and ability usage

### **PlayerClassBase** (`scripts/entities/player/player_class_base.gd`)

**Pattern:** Strategy + Template Method

**Purpose:** Abstract base for character classes

### **EnemyBase** (`scripts/entities/enemies/enemy_base.gd`)

**Pattern:** Component-Based + Data-Driven

**Purpose:** Base enemy that loads configuration from definitions

### **EnemyAIBase** (`scripts/entities/enemies/enemy_ai_base.gd`)

**Pattern:** State Machine + Strategy

**Purpose:** Enemy AI behavior

### **ProjectileBase** (`scripts/entities/projectiles/projectile_base.gd`)

**Pattern:** Object Pool + Flyweight

**Purpose:** Projectile behavior

---

### 3. Combat System

### **CombatSystem** (`scripts/systems/combat/combat_system.gd`)

**Pattern:** Facade + Mediator

**Purpose:** Coordinates all combat interactions

### **DamageCalculator** (`scripts/systems/combat/damage_calculator.gd`)

**Pattern:** Strategy

**Purpose:** Damage calculation formulas

### **StatusEffectManager** (`scripts/systems/combat/status_effect_manager.gd`)

**Pattern:** Component + Observer

**Purpose:** Buffs, debuffs, DoTs

---

### 4. Inventory System

### **InventorySystem** (`scripts/systems/inventory/inventory_system.gd`)

**Pattern:** Facade + Observer

**Purpose:** Inventory management

### **ItemGenerator** (`scripts/systems/inventory/item_generator.gd`)

**Pattern:** Factory + Builder

**Purpose:** Procedural item generation

### **LootTable** (`scripts/systems/inventory/loot_table.gd`)

**Pattern:** Strategy + Weighted Random

**Purpose:** Loot drop determination

---

### 5. Progression System

### **ExperienceSystem** (`scripts/systems/progression/experience_system.gd`)

**Pattern:** Observer

**Purpose:** Experience gain and level-ups

### **StatSystem** (`scripts/systems/progression/stat_system.gd`)

**Pattern:** Component

**Purpose:** Character stat management

### **PermanentProgression** (`scripts/systems/progression/permanent_progression.gd`)

**Pattern:** Memento

**Purpose:** Permanent stat potions and account-wide progression

---

### 6. Tournament System

### **TournamentSystem** (`scripts/systems/tournament/tournament_system.gd`)

**Pattern:** State Machine + Observer

**Purpose:** Tournament management

### **RaceTracker** (`scripts/systems/tournament/race_tracker.gd`)

**Pattern:** Observer

**Purpose:** Cutthroat race tracking

### **LeaderboardSystem** (`scripts/systems/tournament/leaderboard_system.gd`)

**Pattern:** Repository + Cache

**Purpose:** Leaderboard display and updates

---

### 7. Network Synchronization

### **NetworkSynchronizer** (Using Godot’s MultiplayerSynchronizer)

**Pattern:** Observer + State Synchronization

**Purpose:** Synchronize entity state across network

Attached to each networked entity (Player, Enemy, Projectile):

### **StateSynchronizer** (`scripts/network/state_synchronizer.gd`)

**Pattern:** Delta Compression

**Purpose:** Efficient state updates

### **ClientInterpolation** (`scripts/network/interpolation.gd`)

**Pattern:** Interpolation

**Purpose:** Smooth movement on clients

---

### 8. Persistence & Permadeath

### **SaveSystem** (`scripts/systems/persistence/save_system.gd`)

**Pattern:** Memento

**Purpose:** Character save/load

### **PermadeathHandler** (`scripts/systems/persistence/permadeath_handler.gd`)

**Pattern:** Strategy

**Purpose:** Handle permadeath logic

---

### 9. Spawning & Object Pooling

### **SpawnSystem** (`scripts/systems/spawning/spawn_system.gd`)

**Pattern:** Factory + Object Pool

**Purpose:** Entity spawning with pooling

### **WaveSpawner** (`scripts/systems/spawning/wave_spawner.gd`)

**Pattern:** Strategy + Template Method

**Purpose:** Wave-based enemy spawning using factory

---

## Design Patterns Reference

### Complete Pattern Usage Map

| Pattern             | Classes                                                            | Purpose                                                  |
| ------------------- | ------------------------------------------------------------------ | -------------------------------------------------------- |
| **Singleton**       | GameManager, NetworkManager, EventBus, AudioManager                | Global access points                                     |
| **Factory**         | EnemyFactory, ItemFactory, SpellFactory, ProjectileFactory         | Create entities from JSON definitions                    |
| **Service Layer**   | AuthService, CharacterService, InventoryService, TournamentService | Business logic encapsulation                             |
| **Repository**      | CharacterRepository, InventoryRepository, TournamentRepository     | Data access abstraction                                  |
| **Object Pool**     | ProjectileFactory, SpawnSystem                                     | Performance optimization for frequently spawned entities |
| **Builder**         | ItemFactory (with affixes), SpellFactory                           | Complex object construction                              |
| **Observer**        | EventBus, All signal-based systems                                 | Event-driven communication                               |
| **Strategy**        | PlayerClassBase, EnemyAIBase, DamageCalculator                     | Interchangeable algorithms                               |
| **State Machine**   | EnemyAI, TournamentSystem, GameManager                             | State transitions                                        |
| **Command**         | PlayerInput, AbilityCommand                                        | Encapsulate requests                                     |
| **Template Method** | BaseEntity, PlayerClassBase, WaveSpawner                           | Define algorithm skeleton                                |
| **Component**       | All entity component scripts                                       | Composition over inheritance                             |
| **Facade**          | CombatSystem, NetworkManager, AudioManager                         | Simplified interface                                     |
| **Mediator**        | CombatSystem, EventBus                                             | Reduce coupling                                          |
| **Memento**         | SaveSystem, CharacterData                                          | Save/restore state                                       |
| **Flyweight**       | SpellData (shared definitions), ProjectileBase                     | Share common data                                        |
| **Decorator**       | StatusEffect system                                                | Add behavior dynamically                                 |
| **Prototype**       | ItemFactory (item cloning)                                         | Clone existing objects                                   |
| **Data-Driven**     | All factories, DatabaseLoader                                      | Separate data from code                                  |

---

## Network Architecture (NEEDS UPDATE)

We have two netcode patterns in our code.

PvE and monster damage is client authoritative, like in Realm of the mad gods.
PvP is server authoritative.

### Client-Server Model

```
Needs Update
```

### Server Authority (NEEDS UPDATE)

**Server Validates:**

- All combat actions (damage, healing, deaths)
- Movement (anti-speed hacking)
- Item generation and drops
- Experience and level-ups
- Ability usage and cooldowns
- Permadeath triggers

**Clients Handle:** (NEEDS UPDATE)

- Input gathering
- Visual effects and animations
- UI updates
- Prediction (client-side prediction with server reconciliation)
- Audio playback

### RPC Structure

---

## Data Models

### Character Data Model

```
(NEEDS UPDATE)
```

### Item Data Model

```
(NEEDS UPDATE)
```

### Spell Data Model

```
(NEEDS UPDATE)
```

---

## CMS Integration (NEEDS UPDATE)

Needs to be moved out into it’s own CMS.md file

### Overview

The game includes a web-based Content Management System (CMS) that allows designers and balance teams to manage game content without Godot access or game rebuilds.

SEE Astro folder

### CMS Architecture

```
(NEEDS UPDATE)
```

### CMS Features

### 1. Enemy Editor

```
Fields:
- Name (text)
- Health (number)
- Damage (number)
- Speed (number)
- AI Type (dropdown: melee_aggressive, ranged_kiting, etc.)
- Abilities (multi-select from spell list)
- Loot Table (dropdown)
- Experience Reward (number)
- Resistances (key-value pairs)

Actions:
- Create New Enemy
- Clone Existing
- Visual Preview (if possible)
- Preview (shows stats comparison)
- Publish (exports to JSON)
- Archive (soft delete)
```

### 2. Item Editor

```
Fields:
- Item Type (dropdown: weapon, armor, consumable)
- Name (text)
- Base Stats (varies by type)
- Rarity Multipliers (table editor)
- Affix Pool (checkboxes)
- Icon (file upload)
- Value (number)

Features:
- Item Generator Preview (shows sample generated items)
- Stat Comparison Tool
- Bulk Edit (change all swords at once)
```

### 3. Spell Editor

```
Fields:
- Name (text)
- Damage (number)
- Mana Cost (number)
- Cooldown (number)
- Cast Time (number)
- Range (number)
- Projectile (dropdown)
- Effects (array of effect objects)

Features:
- Visual Preview (if possible)
- DPS Calculator
- Class Assignment (which classes can use this spell)
```

### 4. Balance Dashboard

Go API needs to be updated to handle this and store these stats in the Postgres database

```
Analytics:
- Most used items
- Most killed by enemies
- Average time to kill enemies
- Spell usage rates
- Win rates by class

Tools:
- Global damage multiplier slider
- Batch update health values
- Export balance patch
```

### Content Update Flow

### Development Environment

```
1. Designer logs into CMS
2. Edits enemy stats (e.g., increase Goblin health from 50 to 60)
3. Clicks "Save Draft"
4. Tests in dev environment
5. Clicks "Publish"
6. System generates new enemy_database.json
7. Uploads to dev CDN
8. Dev game clients download on next launch
```

### Production Environment

```
1. Designer creates balance patch in CMS
2. Submits for approval
3. Lead Designer reviews changes
4. Approves patch
5. Automated deployment:
   - Generates production JSON files
   - Uploads to production CDN
   - Updates version number
   - Sends webhook notification
6. Game clients check version on launch
7. Downloads new definitions (few KB)
8. Applies new balance immediately
```

### API Endpoints

See docs/api/cms-api.md

### Backend API Structure

### Client-Side Update System

```
NEEDS UPDATE
```

### CMS Database Schema

```sql
NEEDS UPDATE
```

### Live Update Example

**Scenario:** Goblin is too weak in production

```
1. Designer opens CMS
2. Navigates to Enemies → Goblin
3. Changes health: 50 → 75
4. Changes damage: 8 → 12
5. Clicks "Publish"

Server Process:
6. Validates changes
7. Updates database
8. Generates new enemy_database.json
9. Uploads to CDN
10. Increments version: 1.0.0 → 1.0.1
11. Sends webhook to Discord/Slack

Game Process (next launch):
12. Client checks version API
13. Sees 1.0.0 (local) vs 1.0.1 (remote)
14. Downloads enemy_database.json (2KB)
15. EnemyFactory.initialize() reloads definitions
16. All new Goblins spawn with 75 health and 12 damage
17. No game patch required!

Time from change to production: < 5 minutes
```

---

## Implementation Priorities (use Claude Workflows)

Most features exits, but needs refactoring in code, renamed files, moved files, scenes created with proper nodes, folders created, documentation updated and structured.

### Phase 1: Core Systems + Data Foundation

1. Project structure setup
2. **Data-driven architecture:**
   - JSON schema definitions
   - Factory base classes
   - DatabaseLoader implementation
3. Base entity system (data-driven)
4. Player controller and movement
5. Basic networking (client-server connection)
6. Simple combat (projectiles, damage)

### Phase 2: Content Systems + Factories

1. **Complete factory implementations:**
   - EnemyFactory with first 10 enemy definitions
   - ItemFactory with procedural generation
   - SpellFactory with class abilities
   - ProjectileFactory with pooling
2. Enemy AI system
3. Combat system refinement
4. Status effects
5. **JSON content creation** (parallel to development)

### Phase 3: Progression

1. Experience and leveling
2. Character classes (data-driven)
3. Inventory system
4. Equipment system
5. Save/load system
6. **Content expansion:** 50+ enemies, 100+ items in JSON

### Phase 4: Multiplayer Features

1. Backend API integration
2. Authentication
3. Character persistence
4. Permadeath implementation
5. PvP mode
6. **Content updater system** (automatic JSON downloads)

### Phase 7: Polish & Optimization

1. Object pooling optimization
2. Network optimization
3. UI/UX polish
4. Balance tuning (using CMS!)
5. Bug fixes
6. **Live balance testing** with hot updates

---

## Development Guidelines

### Naming Conventions

- **Scripts:** snake_case (e.g., `player_controller.gd`)
- **Scenes:** snake_case (e.g., `main_menu.tscn`)
- **Classes:** PascalCase (e.g., `PlayerController`)
- **Variables:** snake_case (e.g., `max_health`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `MAX_PLAYERS`)
- **Signals:** snake_case (e.g., `health_changed`)
- **RPC functions:** Prefix with `rpc_` or decorator name

### Code Organization

- One class per file
- Group related functionality in folders
- Use autoload sparingly (only for true singletons)
- Prefer composition over inheritance

### Performance Considerations

- Use object pooling for frequently spawned entities (projectiles, effects)
- Minimize RPC calls (batch when possible)
- Cache expensive calculations
- Use dirty flags to avoid redundant updates
- Profile regularly with Godot’s built-in profiler

### Testing Strategy

- Unit tests for business logic (services, calculators)
- Integration tests for systems (combat, inventory)
- Manual testing for gameplay feel
- Network stress testing for multiplayer
- Use GUT (Godot Unit Test) framework
