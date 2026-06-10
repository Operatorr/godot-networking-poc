# Omega Realm — Meadows Biome Style Guide

## Bright Early-Game Peaceful Biome

**Biome:** Mainland > Meadows
**Tone:** Peaceful, bright, safe, welcoming
**Gameplay Role:** Early-game exploration, tutorial-friendly combat, gathering, friendly wildlife, low-pressure encounters
**Visual Style:** Bright top-down pixel art, soft daylight, fantasy meadow charm

---

# 1. Biome Identity

The Meadows biome is the rare place in Omega Realm where the world still feels alive.

It should feel warm, open, colorful, and safe. This is where new players learn movement, gathering, light combat, basic projectile dodging, and friendly-area mechanics. The tone is not dark, brutal, or corrupted. Instead, it should communicate peace, sunlight, flowers, butterflies, wildlife, and gentle magic.

## Core Mood

**“Where the world still remembers how to bloom.”**

## Visual Keywords

- Bright daylight
- Flower fields
- Butterflies
- Rabbits
- Deer
- Bees
- Rainbows
- Gentle wildlife
- Soft grass
- Streams
- White fences
- Small cottages
- Safe zones
- Warm healing magic
- Early-game charm

## Pixel Art Direction

- Use clean silhouettes and readable top-down shapes.
- Avoid harsh shadows and heavy grime.
- Use rounded forms, soft outlines, and cheerful color contrast.
- Keep animations bouncy, light, and playful.
- Magical effects should sparkle, bloom, swirl, or shimmer rather than explode violently.
- The biome should feel beginner-friendly and emotionally safe.

---

# 2. Palette

| Color Name    |       HEX | Usage                                                   |
| ------------- | --------: | ------------------------------------------------------- |
| Sky Blue      | `#7ECDF2` | Clear sky accents, water highlights, UI energy glow     |
| Cloud White   | `#FFFBEA` | Clouds, soft UI backgrounds, petals, gentle highlights  |
| Sunlight Gold | `#FFD866` | Sun rays, sparkles, treasure accents, healing effects   |
| Meadow Green  | `#63B642` | Primary grass, leaves, meadow tiles                     |
| Clover Green  | `#4FAE3A` | Clover patches, vines, healthy foliage                  |
| Soft Moss     | `#9AC56A` | Moss, soft ground variation, calm secondary green       |
| Petal Pink    | `#F6A6C8` | Flowers, butterfly wings, friendly magical effects      |
| Poppy Red     | `#E85B55` | Red flowers, small UI alerts, warm accent color         |
| Lavender      | `#B9A0E8` | Soft magical glow, rare flowers, gentle spell effects   |
| Butter Yellow | `#FFE88A` | Butterflies, pollen, sunlit flowers, spark trails       |
| Rabbit Brown  | `#9B6B3F` | Rabbit markings, wooden props, dirt warmth              |
| Deer Tan      | `#C98945` | Deer sprites, wooden fences, soft earth highlights      |
| Rainbow Teal  | `#63D6C7` | Rainbow magic, healing particles, friendly aura effects |
| Prism Violet  | `#A77BE8` | Prism shards, rare magic, rainbow finish effects        |

## Palette Rules

- Use **Meadow Green**, **Clover Green**, and **Soft Moss** as the dominant terrain colors.
- Use **Cloud White** for clean highlights and UI readability.
- Use **Sunlight Gold**, **Butter Yellow**, **Petal Pink**, and **Rainbow Teal** for positive magical effects.
- Use **Poppy Red** sparingly so it does not feel dangerous.
- Avoid black-heavy shadows. Use warm browns or muted greens for shadow clusters instead.

---

# 3. Creatures

Creatures in the Meadows biome should feel friendly, playful, or only mildly threatening. Even enemies should look like early-game nuisances rather than horrors.

---

## 3.1 Butterfly

### Role

Ambient wildlife, visual charm, magical particles, peaceful biome identity.

### Visual Description

Small colorful butterfly sprite with rounded wings and simple readable body.

### Design Notes

- Wings should use bright symmetrical shapes.
- Create several color variants: yellow, pink, blue, teal, violet.
- Should work both as wildlife and as VFX particles.
- Keep body dark enough to read against flowers and grass.

### Suggested Sprite Size

- 8x8 px
- 12x12 px
- 16x16 px for larger magical butterflies

### Animation Ideas

- 2-frame wing flap
- 4-frame flutter
- Idle hover loop
- Tiny sparkle trail variant

### Palette

- Butter Yellow
- Petal Pink
- Rainbow Teal
- Prism Violet
- Cloud White

---

## 3.2 Sprite

### Role

Friendly magical creature, guide entity, ambient meadow spirit, possible tutorial companion.

### Visual Description

A tiny glowing nature spirit with wings, soft aura, and playful movement.

### Design Notes

- Should feel benevolent and curious.
- Could have butterfly wings, a flower crown, or a glowing seed body.
- Small face or eye dots help with personality.
- Avoid sharp horns, claws, or aggressive forms.

### Suggested Sprite Size

- 16x16 px
- 24x24 px for important NPC version

### Animation Ideas

- Floating idle
- Wing flutter
- Spin sparkle
- Wave / attention ping
- Healing pulse

### Palette

- Rainbow Teal
- Sunlight Gold
- Cloud White
- Lavender
- Petal Pink

---

## 3.3 Meadow Hare

### Role

Early wildlife, gentle movement tutorial creature, possible low-threat chase target.

### Visual Description

Cute rabbit-like creature with large ears, rounded body, tiny paws, and soft neutral colors.

### Design Notes

- Must read instantly as a rabbit from top-down view.
- Large ears are the main silhouette feature.
- Use soft body shapes and small hopping poses.
- Should look harmless and lively.

### Suggested Sprite Size

- 24x24 px
- 32x32 px

### Turnaround Views

- Front
- Back
- Left
- Right
- Hop frame
- Resting frame

### Animation Ideas

- Idle nose twitch
- Hop cycle
- Ear wiggle
- Startle jump
- Burrow / hide

### Palette

- Cloud White
- Rabbit Brown
- Deer Tan
- Petal Pink
- Soft Moss shadow

---

## 3.4 Graze Deer

### Role

Peaceful wildlife, ambient herd creature, early biome mascot.

### Visual Description

Gentle deer or fawn with tan body, white spots, small ears, and graceful legs.

### Design Notes

- Should feel calm and non-hostile.
- Use soft eyes and rounded face.
- White spots help separate body from grass.
- Fawn version is better for early-game peaceful tone.

### Suggested Sprite Size

- 32x32 px
- 40x40 px

### Turnaround Views

- Front
- Back
- Left
- Right
- Grazing pose
- Alert pose

### Animation Ideas

- Grazing loop
- Slow walk
- Ear flick
- Look around
- Gentle hop / flee

### Palette

- Deer Tan
- Rabbit Brown
- Cloud White
- Meadow Green shadow
- Butter Yellow highlight

---

## 3.5 Flower Slime

### Role

First low-threat enemy, harmless-looking training combat target.

### Visual Description

Small round green slime with a flower growing on its head.

### Design Notes

- Should look cute, not gross.
- Give it a smiling or curious face.
- Flower on top creates strong silhouette.
- Movement should be bouncy and slow.

### Suggested Sprite Size

- 24x24 px
- 32x32 px

### Turnaround Views

- Front
- Side
- Back
- Squish frame
- Jump frame
- Damaged frame

### Animation Ideas

- Bounce idle
- Hop attack
- Flower wiggle
- Split into pollen puff
- Friendly blink

### Palette

- Meadow Green
- Clover Green
- Soft Moss
- Petal Pink
- Cloud White

---

## 3.6 Thistle Gremlin

### Role

Playful early enemy, pollen prankster, light ranged attacker.

### Visual Description

Tiny green gremlin or imp with a purple thistle cap, leaf-like ears, and mischievous expression.

### Design Notes

- Should be mildly annoying, not frightening.
- Small body, oversized head, expressive pose.
- Can throw pollen, seeds, or tiny thorns.
- Purple thistle cap makes it readable.

### Suggested Sprite Size

- 24x24 px
- 32x32 px

### Turnaround Views

- Front
- Back
- Left
- Right
- Throwing pose
- Laughing pose

### Animation Ideas

- Idle bounce
- Pollen throw
- Hide behind flower
- Dash away
- Dizzy defeated frame

### Palette

- Clover Green
- Soft Moss
- Prism Violet
- Lavender
- Butter Yellow

---

# 4. Floor Tiles

All floor tiles should be bright, readable, and modular. They should support open-field layouts, gentle paths, tutorial zones, and safe early-game areas.

---

## 4.1 Grass

### Description

Basic healthy meadow grass tile.

### Visual Notes

- Clean green base.
- Subtle blade clusters.
- Very low contrast.
- Good default walkable tile.

### Palette

Meadow Green, Clover Green, Soft Moss.

---

## 4.2 Flower Grass

### Description

Grass tile scattered with small flowers.

### Visual Notes

- Use tiny pink, yellow, white, and lavender flower pixels.
- Avoid over-cluttering the tile.
- Works well near safe zones, cottages, and sprite areas.

### Palette

Meadow Green, Petal Pink, Butter Yellow, Cloud White, Lavender.

---

## 4.3 Clover Patch

### Description

Dense clover growth tile.

### Visual Notes

- Rounder leaf shapes than standard grass.
- Slightly darker green than flower grass.
- Can be used to mark lucky or healing areas.

### Palette

Clover Green, Meadow Green, Soft Moss.

---

## 4.4 Dirt Path

### Description

Soft walking trail through grass.

### Visual Notes

- Warm brown center.
- Grass edges blend naturally into nearby tiles.
- Use small pebbles or footprints for variation.

### Palette

Rabbit Brown, Deer Tan, Soft Moss.

---

## 4.5 Sunny Meadow

### Description

Bright grass tile with sunlight patches.

### Visual Notes

- Use yellow-green highlights.
- Should feel warm and open.
- Good for central field areas.

### Palette

Meadow Green, Sunlight Gold, Butter Yellow, Soft Moss.

---

## 4.6 Pebble Path

### Description

Light stone path tile.

### Visual Notes

- Rounded pale stones.
- Grass visible between stones.
- Suitable for villages, shrines, and safe-zone paths.

### Palette

Cloud White, Soft Moss, Deer Tan, Meadow Green.

---

## 4.7 Stream Edge

### Description

Grass-to-water transition tile.

### Visual Notes

- Clear blue water edge.
- Rounded grassy bank.
- Include tiny reeds or flowers.
- Use sparkling water highlights.

### Palette

Sky Blue, Rainbow Teal, Meadow Green, Cloud White.

---

## 4.8 Rainbow Flower

### Description

Rare flower tile with multicolor blooms.

### Visual Notes

- More magical than normal flower grass.
- Use as a reward, portal marker, or healing area.
- Should feel special but not dangerous.

### Palette

Petal Pink, Butter Yellow, Rainbow Teal, Prism Violet, Cloud White.

---

## 4.9 Soft Moss

### Description

Quiet mossy ground tile.

### Visual Notes

- Softer and slightly muted.
- Good near trees, stones, cottages, and shaded areas.
- Use gentle round clusters.

### Palette

Soft Moss, Clover Green, Meadow Green.

---

## 4.10 Stone Steps

### Description

Light stepping-stone tile.

### Visual Notes

- Rounded white or pale tan stones.
- Moss between cracks.
- Should be clean and friendly.

### Palette

Cloud White, Deer Tan, Soft Moss, Meadow Green.

---

# 5. Environment Tiles and Props

Environment pieces should support peaceful exploration, beginner navigation, village-like landmarks, and safe-area readability.

---

## 5.1 Walls and Architecture

### Low Stone Fence

Small pale stone barrier with moss and flowers.

- **Use:** Soft boundary, garden edge, path guidance.
- **Palette:** Cloud White, Soft Moss, Meadow Green.

### Wooden Gate

Simple rounded wooden garden gate.

- **Use:** Entrance to farms, cottages, tutorial paths.
- **Palette:** Rabbit Brown, Deer Tan, Clover Green.

### Hedge Wall

Dense green hedge with flowers.

- **Use:** Natural wall, maze edge, soft barrier.
- **Palette:** Clover Green, Meadow Green, Petal Pink.

### Little Bridge

Small wooden bridge over streams.

- **Use:** Stream crossing, early exploration landmark.
- **Palette:** Rabbit Brown, Deer Tan, Sky Blue highlights.

### Windmill Fragment

Cute rural landmark piece, such as blades or a small base.

- **Use:** Background structure, village landmark.
- **Palette:** Cloud White, Deer Tan, Sunlight Gold.

### Shrine

Small peaceful stone shrine with flowers or dove motif.

- **Use:** Healing point, checkpoint, safe zone.
- **Palette:** Cloud White, Sunlight Gold, Meadow Green.

### Cottage Ruin

Gentle, non-threatening old cottage wall covered in vines.

- **Use:** Exploration area, loot corner.
- **Palette:** Deer Tan, Rabbit Brown, Soft Moss, Petal Pink.

### Signpost

Wooden sign with flower trim.

- **Use:** Tutorial direction, biome navigation.
- **Palette:** Rabbit Brown, Butter Yellow, Clover Green.

### White Fence

Classic friendly fence section.

- **Use:** Friendly area border, village, farm.
- **Palette:** Cloud White, Meadow Green, Soft Moss.

### Fence Corner

Corner piece for white fence modular set.

- **Use:** Build enclosed safe zones and gardens.
- **Palette:** Cloud White, Meadow Green.

---

# 6. Special / Magical

These assets should feel wondrous and safe. Their glow should suggest healing, curiosity, and discovery.

---

## 6.1 Rainbow Puddle

### Description

A small magical puddle reflecting rainbow colors.

### Use

- Gentle interactable
- Healing pool
- Quest marker
- Decorative magical tile

### Visual Notes

- Soft circular puddle shape.
- Use pastel rainbow highlights.
- Add small sparkle pixels.

### Palette

Sky Blue, Rainbow Teal, Prism Violet, Petal Pink, Sunlight Gold.

---

## 6.2 Butterfly Circle

### Description

A circular pattern of butterflies hovering around a point.

### Use

- Spawn marker
- Safe area marker
- Magical gathering point

### Visual Notes

- Butterflies should form a loose ring.
- Include subtle sparkle trail.
- Keep motion light and playful.

### Palette

Butter Yellow, Petal Pink, Rainbow Teal, Prism Violet.

---

## 6.3 Sparkling Fairy Ring

### Description

A ring of glowing flowers, mushrooms, and sparkles.

### Use

- Teleport marker
- Hidden reward location
- Friendly NPC gathering spot

### Visual Notes

- Circular arrangement.
- White, yellow, and teal sparkles.
- Should look magical but harmless.

### Palette

Cloud White, Sunlight Gold, Rainbow Teal, Soft Moss.

---

## 6.4 Glowing Flower Patch

### Description

Cluster of flowers emitting soft light.

### Use

- Healing tile
- Nighttime visual guide
- Safe path marker

### Visual Notes

- Petals should glow gently.
- Use subtle yellow-white center pixels.
- Avoid harsh bloom.

### Palette

Petal Pink, Butter Yellow, Cloud White, Meadow Green.

---

## 6.5 Light Beam Grass

### Description

Patch of grass with a vertical sunbeam shining down.

### Use

- Respawn-safe area
- Tutorial highlight
- Blessing marker

### Visual Notes

- Soft golden vertical light.
- Grass beneath should be brighter.
- Add floating dust motes.

### Palette

Sunlight Gold, Butter Yellow, Cloud White, Meadow Green.

---

## 6.6 Prism Crystal Patch

### Description

Small cluster of pastel crystals in meadow grass.

### Use

- Rare resource node
- Magical landmark
- Early crafting material source

### Visual Notes

- Crystals should be bright but soft.
- Use rainbow-tinted edges.
- Keep silhouettes chunky and readable.

### Palette

Prism Violet, Rainbow Teal, Sky Blue, Cloud White, Petal Pink.

---

# 7. Props and Decor

Props should make the Meadows feel lived-in, safe, and friendly.

---

## 7.1 Flower Cart

A small wooden cart overflowing with flowers.

- **Use:** Village prop, market area, safe zone decoration.
- **Palette:** Rabbit Brown, Petal Pink, Butter Yellow, Meadow Green.

## 7.2 Beehive

Round golden beehive with tiny bee pixels.

- **Use:** Honey loot source, ambient wildlife prop.
- **Palette:** Sunlight Gold, Butter Yellow, Rabbit Brown.

## 7.3 Birdhouse

Small wooden birdhouse on a post.

- **Use:** Peaceful landmark, decorative prop.
- **Palette:** Rabbit Brown, Deer Tan, Poppy Red, Cloud White.

## 7.4 Picnic Basket

Basket with cloth, fruit, and flowers.

- **Use:** Friendly area decoration, rest marker.
- **Palette:** Rabbit Brown, Cloud White, Poppy Red, Butter Yellow.

## 7.5 Log Bench

Simple cut log bench.

- **Use:** Rest area, camp space, tutorial hub.
- **Palette:** Rabbit Brown, Deer Tan, Soft Moss.

## 7.6 Watering Can

Small blue or silver watering can.

- **Use:** Garden prop, farming hint, NPC area.
- **Palette:** Sky Blue, Cloud White, Rainbow Teal.

## 7.7 Lantern Post

Friendly wooden lantern post with warm glow.

- **Use:** Path marker, village lighting.
- **Palette:** Rabbit Brown, Sunlight Gold, Butter Yellow.

## 7.8 Hay Bale

Rounded hay bundle.

- **Use:** Farm area, cozy prop, cover object.
- **Palette:** Butter Yellow, Sunlight Gold, Rabbit Brown.

## 7.9 Mushroom Stump

Tree stump with mushrooms growing around it.

- **Use:** Forest edge transition, gathering prop.
- **Palette:** Rabbit Brown, Soft Moss, Petal Pink, Cloud White.

## 7.10 Wheelbarrow

Wooden garden wheelbarrow with soil, flowers, or tools.

- **Use:** Farm prop, village detail.
- **Palette:** Rabbit Brown, Deer Tan, Meadow Green, Petal Pink.

---

# 8. Detail Set Dressing

Small decorative sprites used to make the biome feel alive.

## Required Dressing Assets

| Asset          | Description                                                |
| -------------- | ---------------------------------------------------------- |
| Wildflowers    | Tiny clusters of pink, white, yellow, and lavender flowers |
| Mushrooms      | Small friendly red, white, and tan mushrooms               |
| Clovers        | Tiny 3-leaf and 4-leaf clover clusters                     |
| Smooth Stones  | Rounded pale stones for paths and ground detail            |
| Acorns         | Small brown acorns, useful near trees                      |
| Feathers       | White or soft grey feathers from birds                     |
| Carrot Tops    | Small carrot sprouts for garden areas                      |
| Butterflies    | Tiny ambient butterfly sprites                             |
| Grass Tufts    | Short clumps of bright grass                               |
| Cattails       | Stream-edge plants                                         |
| Reeds          | Thin water plants for river edges                          |
| Seed Bags      | Tiny tied cloth bags with seeds                            |
| Tiny Puddles   | Small reflective water patches                             |
| Ladybugs       | Tiny red beetle sprites                                    |
| Bird Nests     | Small nest with eggs                                       |
| Leaf Piles     | Soft yellow-green leaf clusters                            |
| Sticks         | Small fallen twigs                                         |
| Daisy Cluster  | White flowers with yellow centers                          |
| Bee Swarm Dots | Tiny ambient bee pixels                                    |
| Sparkle Motes  | Small magical particles for safe areas                     |

---

# 9. Icons / Loot

Icons should be readable at 16x16 px. Use bright silhouettes and simple shapes.

---

## 9.1 Bloom Tonic

### Description

Small potion bottle filled with green-blue healing liquid.

### Use

Healing item or beginner potion.

### Palette

Rainbow Teal, Cloud White, Meadow Green, Sunlight Gold.

---

## 9.2 Honey Vial

### Description

Tiny jar or vial of golden honey.

### Use

Restoration item, crafting material, bee-related loot.

### Palette

Sunlight Gold, Butter Yellow, Cloud White, Rabbit Brown.

---

## 9.3 Acorn Charm

### Description

Small acorn medallion or lucky charm.

### Use

Starter trinket, nature defense charm.

### Palette

Rabbit Brown, Deer Tan, Clover Green, Sunlight Gold.

---

## 9.4 Rainbow Shard

### Description

Prismatic crystal shard with rainbow highlights.

### Use

Rare early magical crafting component.

### Palette

Rainbow Teal, Prism Violet, Sky Blue, Petal Pink, Cloud White.

---

## 9.5 Wild Seed

### Description

Tiny seed bag or glowing seed.

### Use

Planting, crafting, summoning friendly plants.

### Palette

Rabbit Brown, Clover Green, Butter Yellow.

---

## 9.6 Garden Key

### Description

Golden key with flower-shaped bow.

### Use

Unlocks garden gates, meadow shrines, safe-area chests.

### Palette

Sunlight Gold, Butter Yellow, Cloud White, Meadow Green.

---

## 9.7 Fawn Token

### Description

Round token with a deer or fawn face.

### Use

Friendly faction currency, wildlife quest reward.

### Palette

Deer Tan, Rabbit Brown, Cloud White, Sunlight Gold.

---

## 9.8 Butterfly Brooch

### Description

Small butterfly-shaped brooch with colorful wings.

### Use

Accessory, movement bonus item, charm.

### Palette

Petal Pink, Rainbow Teal, Prism Violet, Butter Yellow.

---

# 10. VFX / Effects

Effects should feel magical, gentle, and readable. No gore-heavy splashes. Combat feedback should remain clear but friendly.

---

## 10.1 Projectiles

### Projectile 1: Pollen Puff

Small yellow cloud projectile.

- **Shape:** Round soft puff.
- **Use:** Flower Slime or Thistle Gremlin attack.
- **Palette:** Butter Yellow, Sunlight Gold, Cloud White.

### Projectile 2: Seed Shot

Small brown-green seed projectile.

- **Shape:** Tiny oval seed with green trail.
- **Use:** Basic early ranged attack.
- **Palette:** Rabbit Brown, Clover Green, Butter Yellow.

### Projectile 3: Rainbow Spark

Fast multicolor sparkle projectile.

- **Shape:** Tiny star with rainbow trail.
- **Use:** Sprite magic, tutorial magic attack.
- **Palette:** Rainbow Teal, Prism Violet, Petal Pink, Sunlight Gold.

### Projectile 4: Petal Dart

Soft pink petal-shaped projectile.

- **Shape:** Curved petal slash.
- **Use:** Flower-based enemy or player ability.
- **Palette:** Petal Pink, Cloud White, Lavender.

### Projectile 5: Butterfly Trail Bolt

Small glowing butterfly-shaped bolt.

- **Shape:** Winged sparkle.
- **Use:** Friendly magic, safe-zone defense.
- **Palette:** Rainbow Teal, Butter Yellow, Prism Violet.

---

## 10.2 Petal / Spark Effects

### Description

Gentle burst effects made of flower petals, small stars, and glitter.

### Required Variants

1. Pink petal burst.
2. Yellow sparkle pop.
3. Rainbow glitter trail.
4. Flower bloom burst.
5. Tiny healing sparkle loop.

### Palette

Petal Pink, Sunlight Gold, Butter Yellow, Rainbow Teal, Cloud White.

---

## 10.3 Leaf / Dust

### Description

Ground-level movement and nature effects.

### Required Variants

1. Leaf swirl.
2. Dust puff.
3. Grass scatter.
4. Soft landing puff.
5. Circular wind swirl.

### Palette

Clover Green, Meadow Green, Soft Moss, Deer Tan, Cloud White.

---

## 10.4 Muzzle / Light Flash

### Description

Bright non-violent flash effects for ranged abilities or early weapons.

### Required Variants

1. Golden light flash.
2. Green nature flash.
3. Blue sparkle flash.
4. Pink magic flash.
5. Rainbow prism flash.

### Palette

Sunlight Gold, Butter Yellow, Rainbow Teal, Petal Pink, Prism Violet.

---

## 10.5 Nature / Magic

### Description

Positive magical effects tied to healing, growth, butterflies, rainbows, and sunlight.

### Required Variants

1. Sunshine ring.
2. Healing bloom burst.
3. Butterfly sparkle trail.
4. Fairy ring pulse.
5. Vine swirl.
6. Rainbow arc.
7. Gentle aura circle.

### Palette

Sunlight Gold, Rainbow Teal, Petal Pink, Prism Violet, Meadow Green, Cloud White.

---

## 10.6 Hit Impacts

### Physical Hit

A soft dust-and-leaf impact.

- **Shape:** Brown dust puff with grass blades.
- **Use:** Basic melee hit or collision.
- **Palette:** Deer Tan, Rabbit Brown, Soft Moss, Cloud White.

### Magical Hit

A colorful sparkle burst.

- **Shape:** Radial starburst with soft particles.
- **Use:** Magic spell contact.
- **Palette:** Prism Violet, Rainbow Teal, Petal Pink, Sunlight Gold.

### Projectile Impact

A small pop with petals, dust, or sparkles.

- **Shape:** Compact contact burst.
- **Use:** Seed shot, pollen puff, spark projectile.
- **Palette:** Butter Yellow, Petal Pink, Clover Green, Cloud White.

---

# 11. UI Motif and HUD

The Meadows UI should feel safe, clear, friendly, and readable. Use light wood, white stone, vines, flowers, clovers, sun icons, and soft rounded frames.

---

## 11.1 Health Bar

### Visual Description

A floral-trimmed health bar with heart icon.

### Design Notes

- Red or pink fill.
- Flower and vine frame.
- Friendly rounded ends.
- Bright white text.

### Suggested Display

`1000 / 1000`

### Palette

Petal Pink, Poppy Red, Cloud White, Meadow Green, Sunlight Gold.

---

## 11.2 Mana Bar

### Visual Description

A soft blue magical bar with water-drop or crystal icon.

### Design Notes

- Blue or teal fill.
- Light magical sparkles.
- Should feel calm and clean.

### Suggested Display

`150 / 150`

### Palette

Sky Blue, Rainbow Teal, Cloud White, Prism Violet.

---

## 11.3 Ammo / Charge Counter

### Visual Description

Compact friendly counter for seeds, arrows, charges, or projectiles.

### Design Notes

- Use seed, arrow, or small charm icon.
- Wooden or white-stone frame.
- Small golden charge pips.

### Suggested Display

`036 / 120`

### Palette

Rabbit Brown, Cloud White, Sunlight Gold, Butter Yellow.

---

## 11.4 Minimap Frame

### Visual Description

A square minimap framed with vines, flowers, and light wood.

### Design Notes

- Corners should have flower clusters.
- Paths should be readable in light tan.
- Water should be bright blue.
- Friendly markers should use blue, yellow, or pink.

### Palette

Meadow Green, Cloud White, Sky Blue, Petal Pink, Sunlight Gold.

---

## 11.5 Inventory / Panel Frame Corners and Borders

### Visual Description

Reusable UI border kit made from wood, white stone, vines, and flowers.

### Required Pieces

1. Top-left corner.
2. Top-right corner.
3. Bottom-left corner.
4. Bottom-right corner.
5. Horizontal wooden border.
6. Vertical wooden border.
7. Floral vine overlay.
8. White stone support pillar.
9. Clover connector.
10. Small flower ornament.

### Palette

Cloud White, Rabbit Brown, Meadow Green, Petal Pink, Sunlight Gold.

---

## 11.6 Faction Flag

### Visual Description

A soft blue or white banner with sun, flower, dove, or butterfly symbol.

### Design Notes

- Should represent friendly early-game territory.
- Use gold trim and small flower decorations.
- Avoid militaristic or aggressive shapes.

### Suggested Symbols

- Sun emblem
- White dove
- Butterfly
- Blooming flower
- Clover wreath

### Palette

Sky Blue, Cloud White, Sunlight Gold, Meadow Green.

---

## 11.7 Safe Zone / Friendly Area

### Visual Description

A clear UI marker or sign showing that the player is in a protected area.

### Design Notes

- Use warm colors and soft shapes.
- Should feel like rest, healing, and growth.
- Can include flowers, butterflies, and a dove.

### Suggested Text

`FRIENDLY AREA`
`REST • HEAL • GROW`

### Palette

Cloud White, Sunlight Gold, Meadow Green, Petal Pink, Sky Blue.

---

## 11.8 Safe Zone Marker

### Visual Description

A circular patch of flowers or glowing grass on the ground.

### Design Notes

- Top-down readable circle.
- Gentle sparkle or sunbeam animation.
- Use as gameplay marker for safety.

### Animation Ideas

- Soft pulsing ring.
- Butterflies orbiting.
- Flowers gently opening.
- Sunlight shimmer.

### Palette

Meadow Green, Butter Yellow, Cloud White, Rainbow Teal.

---

## 11.9 Friendly Area Badge

### Visual Description

A UI badge or sign marking a non-hostile area.

### Design Notes

- Wooden sign or shield badge.
- Flower trim.
- Optional dove or butterfly icon.
- Rounded and welcoming silhouette.

### Suggested Text

`FRIENDLY AREA`
`REST • HEAL • GROW`

### Palette

Rabbit Brown, Cloud White, Sunlight Gold, Meadow Green, Petal Pink.

---

# 12. Sprite Generation Prompt Template

Use this prompt when generating individual Meadows sprites:

```text
Pixel art sprite for Omega Realm, Meadows biome. Bright peaceful early-game fantasy meadow style. Asset: [ASSET NAME]. Top-down readable game sprite, cheerful daylight, soft grass, flowers, butterflies, gentle wildlife, clean silhouette, bright pastel palette, crisp pixel clusters, transparent background, game-ready sprite, no grimdark, no gore, no horror, no painterly rendering.
```

## Example

```text
Pixel art sprite for Omega Realm, Meadows biome. Bright peaceful early-game fantasy meadow style. Asset: Flower Slime idle sprite. Small cute green slime with a pink flower growing on its head, smiling face, rounded body, soft bounce pose, cheerful daylight palette, top-down readable game sprite, crisp pixel clusters, transparent background, game-ready sprite, no grimdark, no gore, no horror.
```

---

# 13. Quality Checklist

Before accepting a Meadows asset, check:

- Does it feel bright, peaceful, and early-game friendly?
- Is the sprite readable from a top-down gameplay camera?
- Does it avoid dark grimdark mood?
- Does the palette feel sunny and clean?
- Are shapes rounded, soft, and welcoming?
- Would a new player feel safe in this area?
- Does it include enough meadow identity: flowers, grass, butterflies, wildlife, sunlight?
- Is it consistent with the rest of the Meadows biome set?
