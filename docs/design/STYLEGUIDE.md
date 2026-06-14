Below is a markdown spec you can copy into your production doc or use as a prompt library for generating individual sprites.

# Omega Realm Pixel Art Style Guide Spec

## Draft v0.1

**Game:** Omega Realm
**Genre:** Brutal top-down multiplayer shooter
**Visual Style:** Grimdark fantasy + cosmic horror, pixel art
**Core Fantasy:** “I survived what killed others.”

---

# 1. Global Pixel Art Direction

Omega Realm uses readable, high-contrast top-down pixel art with brutal gothic-industrial silhouettes and corrupted cosmic horror accents.

## Theme & Atmosphere

### A World Without Hope

There is no salvation coming. The great empires have fallen. The gods are silent—or worse, they are listening. What remains is a galaxy of suffering: endless war, creeping madness, and the slow heat-death of everything that once held meaning. Humanity clings to existence not out of hope, but out of spite.

### Grimdark Fantasy Meets Cosmic Horror

This is a universe where cruelty is law and suffering is eternal. Fascistic death-cults wage holy wars against horrors that make their fanaticism seem reasonable. The enemies you face are not merely dangerous—they are wrong. Geometries that fracture sanity. Entities older than stars, for whom your extinction is not malice but indifference. In the face of such horror, even the most zealous faith becomes a desperate scream into the void.

### Life is Cheap. Death is Cheaper.

No hand-holding. No safety nets. In Omega Realm, you earn every level, every piece of gear, and every breath. The strongest warriors carry scars from a hundred battles—those who don't carry graves. There are no heroes here. Only survivors, and even they are borrowed time.

## Core Fantasy

**"I survived what killed others."**

Players are drawn to Omega Realm for the primal thrill of high-stakes combat. Every dungeon run could be your last. Every loot drop could be your salvation—or the prize someone murders you for.

## Visual Identity

- **Color Palette:** Oppressive blacks, dried blood browns, rusted iron reds, tarnished gold, and cold bone white—punctuated by the sickening glow of eldritch corruption in violets and void-blues
- **Environment:** Brutalist Gothic cathedrals crumbling under centuries of endless war. Industrial hellscapes of iron and ash. Skull-adorned monuments to forgotten martyrs. Dimensional wounds leaking impossible geometries into a world already drowning in misery
- **Enemies:** Corrupted warriors fused eternally to their armor. Daemon-touched abominations that shatter sanity on sight. Shambling masses of the once-faithful. Cosmic entities so vast and indifferent that humanity is merely an afterthought in their unknowable designs
- **Effects:** Weighty, punishing impacts—blood sprays, bone shatters, the grinding of metal against metal. Eldritch magic tears reality itself, leaving wounds in the air that whisper of extinction
- **Atmosphere:** Perpetual twilight. Ash falls like snow. Every surface tells a story of suffering—prayer scrolls nailed to walls, bodies left where they fell, icons defaced by madness. Hope is a fading memory. Faith is the only weapon left. Mercy is weaknes

## Camera & Sprite Rules

- **Primary View:** Top-down / slightly angled top-down, suitable for bullet-hell combat.
- **Character Readability:** Strong silhouettes first, detail second.
- **Lighting:** Harsh rim highlights, low ambient light, warm rust/blood shadows, cold eldritch glow accents.
- **Material Language:**
  - Metal: dark iron, rust, chipped edges, tarnished gold trim.
  - Cloth: torn robes, battle-worn tabards, ash-stained cloaks.
  - Bone: skulls, teeth, rib motifs, pale trophy details.
  - Corruption: glowing violet cracks, void-blue cores, magenta veins.

- **Mood:** No heroism, no cleanliness, no hope. Everything should feel old, violent, cursed, and barely surviving.

## Suggested Sprite Sizes

| Asset Type           |                                   Suggested Size |
| -------------------- | -----------------------------------------------: |
| Loot Icons           |                             16x16 px or 24x24 px |
| Small Props          |                             16x16 px to 32x32 px |
| Large Props          |                             32x32 px to 64x64 px |
| Characters           |                             32x32 px to 48x48 px |
| Large Enemies        |                             48x48 px to 96x96 px |
| Boss / Cosmic Entity |                                        96x96 px+ |
| Tiles                |                             16x16 px or 32x32 px |
| VFX Frames           |                             16x16 px to 64x64 px |
| UI Panels            | Flexible, built from 8x8 or 16x16 modular pieces |

---

# 2. Palette

The palette should feel oppressive and ancient, with muted grimdark base colors punctured by unnatural eldritch highlights.

| Color Name         |       HEX | Usage                                                       |
| ------------------ | --------: | ----------------------------------------------------------- |
| Abyss Black        | `#050706` | Primary background, deepest shadows, void interiors         |
| Ash Grey           | `#555852` | Dust, ash, worn stone, muted highlights                     |
| Iron Slate         | `#252928` | Dark metal, armor plates, panel frames                      |
| Blood Brown        | `#4A1512` | Dried blood, old gore, stained cloth                        |
| Rust Red           | `#8A261F` | Fresh damage, rust, warning UI accents                      |
| Dark Umber         | `#3A211A` | Mud, leather, old wood, deep environmental shadows          |
| Tarnished Gold     | `#9B7428` | Relics, holy trim, medals, elite accents                    |
| Bone White         | `#D8D0BC` | Skulls, teeth, parchment, high-value readability highlights |
| Flesh Taupe        | `#7A6253` | Mutated flesh, skin, worn cloth, organic props              |
| Sulfur Yellow      | `#C69A2E` | Firelight, muzzle flash, toxic glow, divine decay           |
| Void Violet        | `#5B3A8E` | Primary eldritch glow, void energy                          |
| Eldritch Purple    | `#2B183D` | Deep corruption shadows, rift interiors                     |
| Corruption Magenta | `#8A2D55` | Veins, cursed highlights, spell cores                       |
| Void Blue          | `#1D3557` | Cold cosmic energy, star spawn highlights                   |
| Soul Teal          | `#1C6C73` | Ghostly magic, spirit effects, rare UI accents              |

---

# 3. Player Classes

Each player class should have a clear top-down silhouette, readable weapon identity, and faction-neutral grimdark survival look.

## 3.1 Zealot

**Archetype:** Paladin / Fanatic Knight

### Fantasy

A holy warrior whose faith has curdled into violence. The Zealot does not fight because salvation exists; they fight because surrender is heresy.

### Visual Identity

- Heavy gothic armor.
- Skull mask or exposed skull-like helmet.
- Red-black tabard or torn religious cloth.
- Spiked pauldrons.
- Tarnished gold religious trim.
- Bone charms, wax seals, nailed scriptures.
- Large melee weapon: mace, hammer, flail, or cleaver-sword.

### Palette Focus

- Abyss Black
- Iron Slate
- Blood Brown
- Rust Red
- Tarnished Gold
- Bone White

### Sprite Notes

- **Silhouette:** Broad, square, armored.
- **Top-down readability:** Large shoulders, visible weapon head, strong red tabard.
- **Suggested Variants:**
  - Idle front/top-down
  - Side movement
  - Back movement
  - Attack wind-up
  - Heavy impact swing

---

## 3.2 Void Hunter

**Archetype:** Archer / Ranger

### Fantasy

A hunter who stalks the edges of reality, killing horrors from a distance before they can fully enter the world.

### Visual Identity

- Hooded cloak.
- Long coat or ragged mantle.
- Masked or shadowed face.
- Rifle, crossbow, void-bow, or arcane firearm.
- Void-blue and violet glow around weapon sights or ammo.
- Pouches, traps, knives, ammunition belts.

### Palette Focus

- Abyss Black
- Iron Slate
- Dark Umber
- Void Blue
- Void Violet
- Bone White highlights

### Sprite Notes

- **Silhouette:** Narrow, angular, hunched hunter stance.
- **Top-down readability:** Long weapon extending from body.
- **Suggested Variants:**
  - Idle aiming
  - Side strafe
  - Back cloak view
  - Firing frame
  - Reload / draw frame

---

## 3.3 Engineer

### Fantasy

A battlefield mechanic who keeps ancient killing machines alive with rust, prayer, and spite.

### Visual Identity

- Bulky armor mixed with machinery.
- Brass valves, pipes, tanks, tool belts.
- Heavy backpack rig.
- Mechanical gauntlet, shotgun, flamethrower, or rivet cannon.
- Welding visor, goggles, or bald scarred head.
- Industrial hazard details.

### Palette Focus

- Iron Slate
- Rust Red
- Tarnished Gold
- Dark Umber
- Sulfur Yellow
- Ash Grey

### Sprite Notes

- **Silhouette:** Compact and bulky, mechanical backpack visible.
- **Top-down readability:** Wide stance, large tool/weapon shape.
- **Suggested Variants:**
  - Idle holding tool-gun
  - Repair / interact pose
  - Firing heavy weapon
  - Deploying turret
  - Backpack vent glow

---

## 3.4 Plague Seer

**Archetype:** Warlock

### Fantasy

A prophet of rot who reads the future in infection, mutation, and whispers from dying gods.

### Visual Identity

- Hooded plague robes.
- Bone mask, beaked mask, or skull veil.
- Staff, sickle, censer, or cursed pistol.
- Greenish decay optional, but keep main corruption violet/magenta.
- Vials, prayer beads, hanging bones.
- Tattered cloak that trails like smoke.

### Palette Focus

- Abyss Black
- Dark Umber
- Flesh Taupe
- Eldritch Purple
- Corruption Magenta
- Soul Teal

### Sprite Notes

- **Silhouette:** Cloaked, uneven, ritualistic.
- **Top-down readability:** Staff/sickle and trailing robe.
- **Suggested Variants:**
  - Idle ritual pose
  - Casting frame
  - Walking robe sway
  - Poison cloud release
  - Void-channeling frame

---

## 3.5 Warrior

### Fantasy

A brutal frontline survivor who has outlived better soldiers through raw force, pain tolerance, and battlefield cruelty.

### Visual Identity

- Heavy but less holy than Zealot.
- Practical plate armor, chainmail, leather straps.
- Large axe, sword, cleaver, or shield.
- Exposed scars, broken helmet, trophy bones.
- Blood-stained armor with minimal ornament.

### Palette Focus

- Iron Slate
- Ash Grey
- Blood Brown
- Rust Red
- Dark Umber
- Bone White

### Sprite Notes

- **Silhouette:** Wide shoulders, visible weapon arc.
- **Top-down readability:** Big weapon, grounded stance.
- **Suggested Variants:**
  - Idle weapon lowered
  - Charge pose
  - Slash frame
  - Shield block
  - Bloodied damaged variant

---

## 3.6 Rogue

### Fantasy

A graveyard assassin and dungeon scavenger who survives by striking first and vanishing before revenge arrives.

### Visual Identity

- Slim cloak or hood.
- Dual daggers, short blades, pistol-dagger combo, or throwing knives.
- Wrapped face or skeletal half-mask.
- Dark leather, quiet boots, belt pouches.
- Minimal glow; only small violet poison or cursed blade accents.

### Palette Focus

- Abyss Black
- Dark Umber
- Iron Slate
- Blood Brown
- Void Violet
- Bone White edge highlights

### Sprite Notes

- **Silhouette:** Narrow, low, predatory.
- **Top-down readability:** Twin blades or dagger glints.
- **Suggested Variants:**
  - Crouched idle
  - Dash frame
  - Backstab frame
  - Throwing knife frame
  - Stealth shimmer

---

## 3.7 Mage

### Fantasy

A desperate scholar-warrior who tears holes in reality because conventional magic died with the gods.

### Visual Identity

- Battle robes mixed with armored plates.
- Floating tome, staff, orb, or gauntlet focus.
- Void cracks around hands or head.
- Pale mask, glowing eye slits, ritual collar.
- Cloth should feel ancient, burned, and star-stained.

### Palette Focus

- Abyss Black
- Eldritch Purple
- Void Violet
- Void Blue
- Soul Teal
- Bone White

### Sprite Notes

- **Silhouette:** Robed but sharp, with floating magical focus.
- **Top-down readability:** Glowing staff/orb and cloak outline.
- **Suggested Variants:**
  - Idle with floating glyph
  - Spell cast frame
  - Channeling frame
  - Teleport frame
  - Overcharged corruption frame

---

# 4. Enemies

Enemies should feel hostile, readable, and “wrong.” Even humanoid enemies should appear fused, broken, corrupted, or religiously deranged.

---

## 4.1 Fused Warden

### Fantasy

A prison guardian or armored soldier permanently fused to their warplate by corruption.

### Visual Identity

- Heavy blackened armor.
- Red corruption veins through metal seams.
- Spikes, hooks, chains.
- Helmet fused shut.
- One arm may be mutated into a weapon.
- Slow, oppressive, elite enemy feel.

### Palette Focus

- Iron Slate
- Abyss Black
- Rust Red
- Blood Brown
- Bone White
- Corruption Magenta accents

### Sprite Targets

- Idle top-down
- Walk frame
- Attack swing
- Enrage glow
- Death collapse into armor pile

---

## 4.2 Once-Faithful Cultist

### Fantasy

A former believer whose prayers were answered by something that should not have listened.

### Visual Identity

- Ragged robes.
- Skull mask, cracked saint mask, or exposed ruined face.
- Prayer scrolls, beads, candles, hooks.
- Rusted dagger, pistol, censer, or ritual blade.
- Hunched, twitchy posture.

### Palette Focus

- Blood Brown
- Dark Umber
- Bone White
- Rust Red
- Tarnished Gold
- Eldritch Purple accents

### Sprite Targets

- Idle chant
- Walk shuffle
- Knife attack
- Projectile cast
- Panic / frenzy frame

---

## 4.3 Daemon Touched Abomination

### Fantasy

A mass of flesh and armor transformed into a battlefield horror.

### Visual Identity

- Bulky mutated body.
- Tumors, horns, extra limbs, exposed muscle.
- Armor plates embedded in flesh.
- Mouths, eyes, or bone growths.
- Brutal melee monster.

### Palette Focus

- Flesh Taupe
- Blood Brown
- Rust Red
- Corruption Magenta
- Dark Umber
- Bone White

### Sprite Targets

- Idle breathing
- Heavy walk
- Slam attack
- Roar / expose weak point
- Gore burst death

---

## 4.4 Star Spawned Entity

### Fantasy

A cosmic being whose form is only partially compatible with physical reality.

### Visual Identity

- Floating void mass.
- Central eye, star-core, or black hole center.
- Purple tendrils and impossible limb shapes.
- No conventional anatomy.
- Should look dangerous but indifferent.

### Palette Focus

- Abyss Black
- Eldritch Purple
- Void Violet
- Void Blue
- Soul Teal
- Corruption Magenta highlights

### Sprite Targets

- Idle float
- Tendril flare
- Projectile cast
- Teleport distortion
- Dissolve into void particles

---

# 5. Environment Tiles & Props

Environment assets should sell a collapsing gothic-industrial world consumed by corruption.

---

## 5.1 Floor Tiles

### General Direction

Top-down modular tiles for cathedrals, ruined fortresses, crypts, industrial war halls, and corrupted dungeons.

### Tile Ideas

1. Cracked gothic stone tile.
2. Cathedral mosaic tile with worn religious pattern.
3. Iron grate floor.
4. Blood-stained stone.
5. Ash-covered stone.
6. Broken tile with exposed dirt.
7. Rusted metal plate floor.
8. Ritual circle floor marking.
9. Skull-inlaid floor tile.
10. Void-cracked stone tile.

### Sprite Notes

- Tile size: 16x16 or 32x32.
- Avoid overly bright contrast except on hazards or corruption.
- Use slight edge variations for organic tiling.

---

## 5.2 Walls and Architecture

### General Direction

Walls should feel massive, oppressive, brutalist, and religiously militarized.

### Asset Ideas

1. Gothic stone wall segment.
2. Crumbling cathedral arch.
3. Iron-barred gate.
4. Skull-carved pillar.
5. Broken shrine alcove.
6. Industrial pipe wall.
7. Rusted metal barricade.
8. Defaced holy icon.
9. Tall black door with tarnished gold trim.
10. Collapsed masonry wall.

### Sprite Notes

- Include modular straight, corner, broken, and doorway variants.
- Use strong shadows under wall lips for top-down readability.

---

## 5.3 Special / Corrupted

### General Direction

Corruption assets should look like reality is cracking open.

### Asset Ideas

1. Purple-veined floor crack.
2. Void rift wound.
3. Floating glyph scar.
4. Pulsing corruption crystal.
5. Flesh-metal growth.
6. Star-speckled black portal.
7. Magenta infection spreading across stone.
8. Dimensional seam with blue-violet glow.

### Sprite Notes

- Use animated variants where possible.
- Glow should be controlled, not neon everywhere.
- Best accents: Void Violet, Eldritch Purple, Corruption Magenta, Void Blue, Soul Teal.

---

## 5.4 Seven Props and Decor

### 1. Skull Monument

A small shrine or battlefield marker made from skulls, iron, and candle wax.

### 2. Iron Brazier

A gothic fire bowl with sulfur-yellow flame and rusted metal legs.

### 3. Hanging Lantern

A dim caged lantern with tarnished gold frame and smoky light.

### 4. Chain Fence

A low industrial barrier made from chains, spikes, and iron posts.

### 5. War Banner

A torn blood-red banner with defaced religious symbol.

### 6. Gore Altar

A ritual slab covered in dried blood, bones, and nailed prayer strips.

### 7. Cage Reliquary

A small barred cage containing bones, relic fragments, or a cursed skull.

---

## 5.5 Thirteen Detail Set Dressings

Small clutter assets used to make rooms feel lived-in, desecrated, or freshly ruined.

### 1. Nailed Prayer Scrolls

Parchments nailed into stone or wood, edges curled and stained.

### 2. Loose Parchments

Scattered lore sheets, maps, or heretical scriptures.

### 3. Candle Cluster

Small group of candles, some melted into bone-like wax piles.

### 4. Bone Pile

Ribs, skull fragments, femurs, and dust.

### 5. Blood Smear

Directional streak of dried or fresh blood.

### 6. Ash Pile

Soft grey-black debris pile, useful for ruined floors.

### 7. Broken Chains

Scattered iron chain links and shackles.

### 8. Spent Shells

Small brass casings for shooter readability.

### 9. Ritual Bowl

Dark metal bowl filled with blood, ash, or glowing corruption.

### 10. Defaced Icon

Small broken holy icon scratched over with madness marks.

### 11. Rusted Tools

Hammer, wrench, chisel, or bone saw.

### 12. Small Void Crack

Tiny animated corruption fissure for floor decoration.

### 13. Corpse Remnant

Partial body, cloak scrap, or armored hand left where someone died.

---

# 6. Icons / Loot

Icons should be readable at 16x16, with clean silhouettes and one strong highlight color.

---

## 6.1 Stat Potion

### Visual

Small glass vial filled with blood-red liquid.

### Details

- Cork or metal cap.
- Tiny shine highlight.
- Optional skull label or wax seal.

### Palette

Rust Red, Blood Brown, Bone White, Iron Slate.

---

## 6.2 Ammo

### Visual

Bundle of bullets, cartridges, bolts, or arcane rounds.

### Details

- Use tarnished brass casing.
- Dark tips or red/void charge tips.
- Stack of 3 for readability.

### Palette

Tarnished Gold, Iron Slate, Sulfur Yellow, Bone White.

---

## 6.3 Relic

### Visual

Small ornate religious artifact, cross-like or sunburst-like.

### Details

- Tarnished gold frame.
- Bone-white center.
- Slight red or violet curse mark.

### Palette

Tarnished Gold, Bone White, Rust Red, Eldritch Purple.

---

## 6.4 Skull Token

### Visual

Coin or medallion with skull face.

### Details

- Circular or shield-like frame.
- Skull should be the main silhouette.
- Use as death currency or leaderboard token.

### Palette

Bone White, Tarnished Gold, Iron Slate, Abyss Black.

---

## 6.5 Cursed Artifact

### Visual

Purple-black orb, idol, or gem locked in metal.

### Details

- Violet glow.
- Small tendrils or cracks.
- Must feel dangerous to touch.

### Palette

Eldritch Purple, Void Violet, Corruption Magenta, Iron Slate.

---

## 6.6 Key

### Visual

Gothic iron or gold key.

### Details

- Skull or omega-shaped bow.
- Jagged teeth.
- Readable silhouette even at small size.

### Palette

Tarnished Gold, Iron Slate, Bone White.

---

## 6.7 Armor Shard

### Visual

Broken piece of armor plate or shield fragment.

### Details

- Chipped metal edge.
- Small blood or rust detail.
- Could indicate crafting material.

### Palette

Iron Slate, Ash Grey, Rust Red, Bone White highlight.

---

## 6.8 Leaderboard

### Visual

Trophy, skull cup, or ranked sigil.

### Details

- Should feel prestigious but grim.
- Use gold sparingly.
- Optional blood-red rank mark.

### Palette

Tarnished Gold, Bone White, Rust Red, Abyss Black.

---

# 7. VFX / Effects — Top-Down

Effects should be punchy, readable, and brutal. Each VFX should work as a short animation sequence.

---

## 7.1 Five Projectiles

### Projectile 1: Rust Bullet

A fast physical bullet with sulfur muzzle trail.

- **Shape:** Small horizontal streak.
- **Palette:** Sulfur Yellow, Tarnished Gold, Rust Red.
- **Use:** Guns, rifles, pistols.

### Projectile 2: Blood Bolt

A red piercing projectile.

- **Shape:** Needle-like slash bolt.
- **Palette:** Rust Red, Blood Brown, Bone White highlight.
- **Use:** Cultist magic, cursed weapons.

### Projectile 3: Void Orb

A slow glowing purple orb.

- **Shape:** Round core with dark center.
- **Palette:** Eldritch Purple, Void Violet, Corruption Magenta.
- **Use:** Mage, Star Spawn, rift enemies.

### Projectile 4: Soul Shard

A cold blue-white shard projectile.

- **Shape:** Diamond or comet shard.
- **Palette:** Void Blue, Soul Teal, Bone White.
- **Use:** Ghost magic, elite enemies.

### Projectile 5: Corruption Spiral

A swirling tendril projectile.

- **Shape:** Small spiral or hooked trail.
- **Palette:** Void Violet, Corruption Magenta, Abyss Black.
- **Use:** Boss patterns, corruption zones.

---

## 7.2 Blood and Gore

### Visual

Top-down blood splashes, arcs, droplets, pools, and meat fragments.

### Required Variants

1. Small hit spurt.
2. Directional slash spray.
3. Radial explosion.
4. Blood pool.
5. Drag smear.

### Palette

Blood Brown, Rust Red, Dark Umber, Abyss Black.

---

## 7.3 Bone / Shards

### Visual

Bone fragments and armor shards bursting from impacts.

### Required Variants

1. Small bone chip scatter.
2. Radial shard burst.
3. Large rib / skull fragment.
4. Mixed bone and metal debris.
5. Fading dust frame.

### Palette

Bone White, Ash Grey, Iron Slate, Dark Umber.

---

## 7.4 Muzzle Flash

### Visual

Short, bright weapon-fire bursts.

### Required Variants

1. Small pistol flash.
2. Wide shotgun flash.
3. Long rifle flash.
4. Heavy cannon flash.
5. Arcane firearm flash.

### Palette

Sulfur Yellow, Bone White, Rust Red, Tarnished Gold.

---

## 7.5 Corruption / Void

### Visual

Unnatural purple-blue magical distortions.

### Required Variants

1. Small void spark.
2. Purple smoke curl.
3. Rift opening.
4. Glyph ring.
5. Tentacle flare.
6. Void collapse.
7. Star-blue particle burst.

### Palette

Abyss Black, Eldritch Purple, Void Violet, Corruption Magenta, Void Blue, Soul Teal.

---

## 7.6 Hit Impacts

### 7.6.1 Cut / Hit Impact

Physical melee hit effect.

- **Shape:** Sharp red slash arc with bone-white spark.
- **Palette:** Rust Red, Blood Brown, Bone White.
- **Animation:** Slash line appears, expands, breaks into droplets.

### 7.6.2 Spell Impact

Magical explosion effect.

- **Shape:** Circular glyph burst or radial violet crack.
- **Palette:** Void Violet, Corruption Magenta, Soul Teal.
- **Animation:** Core flash, ring expansion, particle fade.

### 7.6.3 Projectile Impact

Bullet or ranged hit.

- **Shape:** Small spark burst with debris.
- **Palette:** Sulfur Yellow, Bone White, Ash Grey, Rust Red.
- **Animation:** Contact spark, smoke puff, debris fade.

---

# 8. UI Motif and HUD

The UI should look like a grim relic-machine: gothic metal, skulls, rivets, worn iron, blood-red fill bars, and bone-white pixel type.

---

## 8.1 Health Bar

### Visual

A long horizontal gothic frame with skull ornament on the left.

### Details

- Red fill.
- Dark metal casing.
- Bone-white numbers.
- Chipped and riveted frame.

### Palette

Rust Red, Blood Brown, Iron Slate, Bone White, Abyss Black.

### Suggested States

1. Full health.
2. Damaged.
3. Critical flashing.
4. Poisoned / corrupted overlay.

---

## 8.2 Mana Bar

### Visual

A matching horizontal bar using void energy instead of blood.

### Details

- Violet or blue fill.
- Small arcane icon or cracked gem on the left.
- Optional flickering corruption particles.

### Palette

Void Violet, Void Blue, Soul Teal, Eldritch Purple, Bone White.

### Suggested States

1. Full mana.
2. Drained.
3. Overcharged.
4. Corrupted mana lock.

---

## 8.3 Ammo / Projectile / Charge Counter

### Visual

A compact gothic-industrial counter panel.

### Details

- Large pixel number readout.
- Bullet, shard, or charge icon.
- Metal plate backing.
- Small ammo-stack indicator.

### Palette

Iron Slate, Tarnished Gold, Bone White, Sulfur Yellow, Abyss Black.

### Suggested Variants

1. Bullet ammo counter.
2. Arrow / bolt counter.
3. Magic charge counter.
4. Cooldown charge pips.

---

## 8.4 Permadeath Indicator

### Visual

A large skull emblem framed by iron, chains, and red warning text.

### Details

- Skull should dominate.
- Red “PERMADEATH” label.
- Optional cracked frame or blood-drip animation.
- Must feel final and threatening.

### Palette

Bone White, Rust Red, Blood Brown, Iron Slate, Abyss Black.

### Suggested States

1. Hardcore mode active.
2. Character dead.
3. Death recap.
4. Leaderboard legacy marker.

---

## 8.5 Minimap Frame

### Visual

Square ornate frame around a simple dungeon map.

### Details

- Gothic corners.
- Small skull or omega compass marks.
- Dark grey room shapes.
- Red player marker or danger marker.

### Palette

Iron Slate, Abyss Black, Ash Grey, Tarnished Gold, Rust Red.

### Suggested Elements

1. Player marker.
2. Boss room marker.
3. Portal marker.
4. Corruption zone marker.
5. Exit marker.

---

## 8.6 Inventory / Panel Frame Corners and Borders

### Visual

Modular UI frame pieces for menus, inventory, tooltips, and popups.

### Required Pieces

1. Top-left corner.
2. Top-right corner.
3. Bottom-left corner.
4. Bottom-right corner.
5. Horizontal border segment.
6. Vertical border segment.
7. Ornate divider.
8. Small skull ornament.
9. Chain connector.
10. Red cloth banner accent.

### Palette

Iron Slate, Abyss Black, Tarnished Gold, Bone White, Rust Red.

### Style Notes

- Corners should be heavy and gothic.
- Borders should tile cleanly.
- Use rivets, spikes, chains, skulls, and worn metal scratches.
- Menus should look like corrupted religious war machinery, not clean fantasy parchment.

---

# 9. Quality Checklist

Before accepting any sprite, check:

- Does the silhouette read instantly?
- Does it match the top-down shooter camera?
- Does it feel brutal, old, cursed, and war-torn?
- Is the palette restrained?
- Are corruption colors used as accents, not everywhere?
- Is the asset readable at gameplay size?
- Does it fit next to the other Omega Realm sprites?
- Does it communicate survival, violence, decay, and cosmic dread?
