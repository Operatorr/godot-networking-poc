> ⚠️ **SUPERSEDED (2026-06).** This bright, cheerful style guide describes the *old* Sanctuary and no
> longer reflects the implemented town. The Sanctuary was redesigned into a grim, ruined gothic
> pilgrim city (Diablo/Tristram tone). The current art direction, palette, and layout are the system
> of record in [`sanctuary-redesign-spec.md`](sanctuary-redesign-spec.md) (theme/palette) and
> [`sanctuary-layout.md`](sanctuary-layout.md) (grid layout). Implementation lives in
> `client/scripts/levels/town/` (`sanctuary_town_world.gd`, `sanctuary_props.gd`) +
> `client/assets/shaders/town/`. This file is retained only for historical reference.

Here is the markdown **Light Town / Sanctuary Style Guide** based on the look you liked.

# Omega Realm — Town / Sanctuary Style Guide

## Light, Friendly, Colorful Safe-Hub Biome

**Biome:** Town / Sanctuary
**Tone:** Bright, peaceful, safe, colorful, welcoming
**Gameplay Role:** Player hub, healing area, vendors, crafting, quests, storage, social interaction, early-game recovery
**Visual Style:** Cheerful top-down pixel art, clean medieval-fantasy sanctuary, soft daylight, flowers, banners, fountains, doves, warm homes

---

# 1. Biome Identity

The Town / Sanctuary is the player’s safe place.

It should feel like the world outside may be dangerous, but here there is warmth, life, color, and community. This is where players rest, recover, repair gear, buy supplies, craft items, accept quests, meet NPCs, and feel protected.

The style should be bright and inviting, but still fantasy-adventure grounded. It should not look like a modern town. It should feel like a magical medieval sanctuary with gardens, stone paths, cozy houses, market stalls, fountains, friendly animals, and protective magic.

## Core Mood

**“Where wanderers rest and hope takes root.”**

## Visual Keywords

- Safe haven
- Bright daylight
- Warm stone
- Cream plaster walls
- Flower boxes
- Market stalls
- Doves
- Healing fountains
- Lanterns
- Blue banners
- Gold trim
- Garden paths
- Friendly NPCs
- Cozy buildings
- Protective magic
- Quest hub
- Crafting hub
- Sanctuary badge

## Pixel Art Direction

- Clean top-down or slightly top-down perspective.
- Soft outlines and readable silhouettes.
- Bright, cheerful colors.
- No gore, horror, decay, or corruption.
- Use flowers, vines, birds, banners, light stone, and gold trim.
- Props should look functional and friendly.
- UI should feel polished, warm, and safe.

---

# 2. Palette

| Color Name      |       HEX | Usage                                                     |
| --------------- | --------: | --------------------------------------------------------- |
| Sky Blue        | `#6EC7F2` | Sky accents, banners, water highlights, mana UI           |
| Cloud White     | `#FFFBEF` | Clouds, plaster highlights, UI backgrounds, dove feathers |
| Sun Gold        | `#FFD36A` | Sunlight, coins, trim, warm UI highlights                 |
| Sanctuary Cream | `#F7E7C4` | Main panel color, plaster walls, parchment, safe-zone UI  |
| Warm Stone      | `#BFAF94` | Cobblestone, plaza stones, fountain stone                 |
| Meadow Green    | `#70B94A` | Grass, garden areas, vines, foliage                       |
| Clover Green    | `#4FA33D` | Hedge, clover, healthy plant accents                      |
| Petal Pink      | `#F3A6BE` | Flowers, blossom arches, friendly sparkles                |
| Poppy Red       | `#E85345` | Apples, flower accents, small warning highlights          |
| Lavender        | `#BDA7E8` | Gentle magic, rare flowers, soft spell accents            |
| Butter Yellow   | `#FFE680` | Flowers, sunlit props, sparkles, friendly highlights      |
| Soft Teal       | `#62C9C1` | Healing water, mana glow, fountain magic                  |
| Honey Brown     | `#B8793A` | Wood, baskets, benches, carts, market stalls              |
| Brick Red       | `#C65B4A` | Roof tiles, brickwork, warm architecture accents          |
| Lantern Gold    | `#E7A93C` | Lantern glow, metal trim, holy light effects              |
| Banner Blue     | `#3C8CCF` | Town banners, guard uniforms, sanctuary iconography       |

## Palette Rules

- Use **Sanctuary Cream** and **Cloud White** as the main light surfaces.
- Use **Warm Stone** for paths, walls, plaza tiles, and neutral grounding.
- Use **Meadow Green** and **Clover Green** to keep the town alive and garden-like.
- Use **Banner Blue** and **Sun Gold** for official sanctuary identity.
- Use **Petal Pink**, **Butter Yellow**, and **Lavender** for flowers and friendly magic.
- Use **Brick Red** for roofs and cozy building accents.
- Keep contrast clean and readable, but avoid harsh black shadows.

---

# 3. Floor Tiles

Floor tiles should support town navigation, markets, gardens, courtyards, and safe-zone landmarks.

---

## 3.1 Cobblestone Path

### Description

A friendly stone walking path made from rounded pale stones.

### Use

Main roads, town center paths, vendor streets.

### Visual Notes

- Rounded stones, not sharp rubble.
- Small moss or flower pixels between stones.
- Should tile smoothly in all directions.

### Palette

Warm Stone, Cloud White, Sanctuary Cream, Soft Moss-style green accents.

---

## 3.2 Sunlit Plaza Tile

### Description

Decorative stone plaza tile with circular or radial pattern.

### Use

Town square, fountain plaza, quest hub center.

### Visual Notes

- Use engraved circular pattern.
- Slight golden highlights.
- Should feel official and welcoming.

### Palette

Warm Stone, Sanctuary Cream, Sun Gold, Cloud White.

---

## 3.3 Flower Path

### Description

Stone or dirt path bordered by flowers.

### Use

Garden walkways, shrine approach, NPC homes.

### Visual Notes

- Path center should remain readable.
- Flowers should decorate edges.
- Use mixed pink, yellow, and white flowers.

### Palette

Warm Stone, Meadow Green, Petal Pink, Butter Yellow, Cloud White.

---

## 3.4 Trimmed Grass

### Description

Clean maintained grass tile.

### Use

Town lawns, gardens, safe areas, cottage yards.

### Visual Notes

- Smooth green base.
- Less wild than meadows.
- Add small clover or flower variation sparingly.

### Palette

Meadow Green, Clover Green, Butter Yellow.

---

## 3.5 Market Rug Tile

### Description

Decorative rug tile used under stalls or vendor spaces.

### Use

Market area, merchant district, festival zone.

### Visual Notes

- Warm patterned fabric.
- Use repeating geometric motifs.
- Should be colorful but not noisy.

### Palette

Poppy Red, Brick Red, Sun Gold, Banner Blue, Sanctuary Cream.

---

## 3.6 Wooden Floor

### Description

Clean wood plank tile.

### Use

Inn interiors, shop interiors, bridges, crafting stations.

### Visual Notes

- Warm planks with subtle grain.
- Use plank seams for readability.
- Avoid dirty or broken appearance.

### Palette

Honey Brown, Deer Tan-like tan, Warm Stone shadows.

---

## 3.7 Fountain Rim Tile

### Description

Circular or curved stone tile around fountains.

### Use

Healing fountain, town center fountain, magical water source.

### Visual Notes

- Pale stone rim with blue water highlights.
- Include small sparkle pixels near water.
- Should support circular fountain layouts.

### Palette

Warm Stone, Cloud White, Sky Blue, Soft Teal.

---

## 3.8 Bridge Plank Tile

### Description

Wooden bridge tile for small streams and canals.

### Use

Canal crossings, garden bridges, town entrances.

### Visual Notes

- Horizontal or vertical plank variants.
- Rope or nail details optional.
- Should look sturdy and safe.

### Palette

Honey Brown, Warm Stone, Lantern Gold highlights.

---

# 4. Environment Tiles and Props

Town environment assets should feel clean, lived-in, and safe. Buildings should be bright, cozy, and readable from a top-down perspective.

---

## 4.1 Cottage Wall

### Description

Small home wall segment with light plaster, wood trim, and flower detail.

### Use

Residential buildings, NPC homes, tutorial hub.

### Visual Notes

- Cream plaster base.
- Honey-brown beams.
- Optional flower box.

### Palette

Sanctuary Cream, Honey Brown, Cloud White, Petal Pink.

---

## 4.2 Timber House Wall

### Description

Classic timber-frame wall segment.

### Use

Shops, homes, inns, crafting buildings.

### Visual Notes

- Wooden beams should be thick and readable.
- Light plaster between beams.
- Add small window or flower pot variants.

### Palette

Honey Brown, Sanctuary Cream, Warm Stone.

---

## 4.3 White Plaster Wall

### Description

Clean white or cream wall for important sanctuary buildings.

### Use

Healer house, shrine, guild hall, town hall.

### Visual Notes

- Smooth light surface.
- Minimal wear.
- Gold or blue trim optional.

### Palette

Cloud White, Sanctuary Cream, Sun Gold, Banner Blue.

---

## 4.4 Red Roof Segment

### Description

Warm red tile roof piece.

### Use

Homes, inns, shops.

### Visual Notes

- Rounded roof tiles.
- Slight highlight on top edge.
- Use modular straight, corner, and ridge variants.

### Palette

Brick Red, Poppy Red, Honey Brown, Sun Gold highlight.

---

## 4.5 Blue Roof Segment

### Description

Blue roof tile piece for official or magical buildings.

### Use

Healer, sanctuary hall, town guard post, mage shop.

### Visual Notes

- Clean blue tiles.
- Gold trim works well.
- Should feel slightly more important than red roof.

### Palette

Banner Blue, Sky Blue, Sun Gold, Cloud White.

---

## 4.6 Arched Doorway

### Description

Rounded wooden or stone doorway.

### Use

Entrances, shops, homes, shrine doors.

### Visual Notes

- Strong arch silhouette.
- Visible handle or gold hinge.
- Flower or lantern variant optional.

### Palette

Honey Brown, Warm Stone, Sanctuary Cream, Lantern Gold.

---

## 4.7 Shopfront Window

### Description

Decorative shop window with awning or goods display.

### Use

Merchants, crafting shops, inns.

### Visual Notes

- Clear square or arched window.
- Add small shelf, cloth awning, or flower box.
- Should read as interactive.

### Palette

Banner Blue, Honey Brown, Sanctuary Cream, Petal Pink.

---

## 4.8 Garden Fence

### Description

Short friendly fence for gardens and safe spaces.

### Use

Yards, farms, flower gardens, NPC boundaries.

### Visual Notes

- Rounded posts.
- White or honey wood variants.
- Flowers or vines on fence.

### Palette

Cloud White, Honey Brown, Meadow Green, Petal Pink.

---

## 4.9 Stone Arch

### Description

Decorative town archway with vines and flowers.

### Use

District entrances, garden gates, shrine paths.

### Visual Notes

- Pale stone structure.
- Flower growth around edges.
- Should frame entrances beautifully.

### Palette

Warm Stone, Cloud White, Meadow Green, Petal Pink.

---

## 4.10 Clocktower Fragment

### Description

Small clocktower wall or roof segment.

### Use

Town square landmark, timekeeping building.

### Visual Notes

- Clock face should be readable.
- Use blue or gold accents.
- Should feel civic and important.

### Palette

Warm Stone, Banner Blue, Sun Gold, Cloud White.

---

## 4.11 Shrine Alcove

### Description

Small sacred wall niche or statue alcove.

### Use

Sanctuary shrine, healer area, blessing station.

### Visual Notes

- Dove, sun, or omega-like icon.
- Soft glow.
- Small flowers or candles.

### Palette

Cloud White, Sanctuary Cream, Sun Gold, Soft Teal.

---

# 5. Special / Magical

Special tiles should communicate safety, healing, travel, blessings, and sanctuary protection.

---

## 5.1 Healing Fountain Tile

### Description

A bright fountain tile with healing water and flowers.

### Use

Main healing station, town center, player recovery point.

### Visual Notes

- Clear blue or teal water.
- White stone basin.
- Flower trim around base.
- Gentle sparkle particles.

### Suggested Animation

- Water shimmer.
- Soft healing sparkle.
- Tiny fountain splash loop.

### Palette

Sky Blue, Soft Teal, Cloud White, Warm Stone, Petal Pink.

---

## 5.2 Sanctuary Sigil Tile

### Description

A decorative floor sigil representing protection and safe-zone status.

### Use

Town center, shrine floor, safe-zone boundary.

### Visual Notes

- Square or circular sigil tile.
- Use sun, dove, shield, or omega-inspired symbol.
- Should be official and readable.

### Suggested Animation

- Subtle golden pulse.
- Soft blue outline shimmer.

### Palette

Banner Blue, Sun Gold, Sanctuary Cream, Cloud White.

---

## 5.3 Glowing Lantern Tile

### Description

A lantern tile that marks safe paths or interactable town routes.

### Use

Road markers, night lighting, quest guidance.

### Visual Notes

- Lantern should be warm and cozy.
- Base can be stone or wood.
- Use small halo glow.

### Suggested Animation

- Gentle flame flicker.
- Soft glow pulse.

### Palette

Lantern Gold, Butter Yellow, Honey Brown, Warm Stone.

---

## 5.4 Blossom Arch

### Description

A flower-covered archway for town entrances or garden paths.

### Use

Safe-zone entrance, wedding/festival decor, garden gate.

### Visual Notes

- Rounded arch silhouette.
- Pink and white flowers.
- Green vine structure.

### Suggested Animation

- Falling petals.
- Small butterfly idle.

### Palette

Petal Pink, Cloud White, Meadow Green, Clover Green.

---

## 5.5 Portal

### Description

A friendly sanctuary travel portal for fast travel or safe hub return.

### Use

Fast travel, respawn area, dungeon exit return point.

### Visual Notes

- Should not look dangerous.
- Use circular stone base with soft blue-gold light.
- Include rune ring, floating motes, and gentle vertical shimmer.
- Avoid dark void colors.

### Suggested Animation

- Rotating rune ring.
- Soft teal-blue inner glow.
- Gold sparkle particles.
- Gentle upward light beam.

### Palette

Soft Teal, Sky Blue, Sun Gold, Cloud White, Lavender.

---

# 6. Props and Decor

Props should make the Town / Sanctuary feel useful, inhabited, and emotionally safe.

---

## 6.1 Market Stall

A colorful stall with cloth awning and goods.

- **Use:** Merchant area, town square.
- **Palette:** Banner Blue, Poppy Red, Honey Brown, Sun Gold.

## 6.2 Bench

Simple wooden bench for resting.

- **Use:** Plaza, gardens, fountain area.
- **Palette:** Honey Brown, Warm Stone.

## 6.3 Flower Cart

Cart full of flowers.

- **Use:** Market decoration, gardener area.
- **Palette:** Honey Brown, Petal Pink, Butter Yellow, Meadow Green.

## 6.4 Fountain

Standalone decorative or healing fountain.

- **Use:** Town center, sanctuary plaza.
- **Palette:** Cloud White, Warm Stone, Sky Blue, Soft Teal.

## 6.5 Lantern Post

Tall friendly lantern post.

- **Use:** Paths, roads, town entrances.
- **Palette:** Honey Brown, Lantern Gold, Butter Yellow.

## 6.6 Signpost

Wooden signpost for directions and quest areas.

- **Use:** Navigation, tutorial markers.
- **Palette:** Honey Brown, Butter Yellow, Meadow Green.

## 6.7 Mailbox

Small red or blue mailbox.

- **Use:** Courier area, player housing, letter quests.
- **Palette:** Poppy Red, Banner Blue, Honey Brown.

## 6.8 Barrel

Simple storage barrel.

- **Use:** Market, inns, crafting areas.
- **Palette:** Honey Brown, Warm Stone, Lantern Gold.

## 6.9 Crate

Wooden crate for supplies.

- **Use:** Vendor stock, crafting materials.
- **Palette:** Honey Brown, Warm Stone.

## 6.10 Potted Plant

Small clay pot with flowers or herbs.

- **Use:** Windows, market stalls, gardens.
- **Palette:** Brick Red, Meadow Green, Petal Pink.

## 6.11 Well

Stone town well with wooden roof or bucket.

- **Use:** Central utility prop, village landmark.
- **Palette:** Warm Stone, Honey Brown, Sky Blue.

## 6.12 Birdbath

Small stone birdbath with water and birds.

- **Use:** Peaceful garden decor.
- **Palette:** Cloud White, Warm Stone, Sky Blue.

## 6.13 Picnic Table

Wooden table with cloth, bread, or flowers.

- **Use:** Rest area, inn garden, social hub.
- **Palette:** Honey Brown, Cloud White, Poppy Red, Petal Pink.

## 6.14 Notice Board

Wooden board covered with quests, notes, and flyers.

- **Use:** Quest hub, town announcements.
- **Palette:** Honey Brown, Sanctuary Cream, Lantern Gold.

## 6.15 Hanging Banner

Blue and gold sanctuary banner.

- **Use:** Town identity, official buildings, safe zone markers.
- **Palette:** Banner Blue, Sun Gold, Cloud White.

---

# 7. Detail Set Dressing

Small sprites used to add life and warmth to streets, shops, gardens, and interiors.

| Asset         | Description                                             |
| ------------- | ------------------------------------------------------- |
| Tiny Flowers  | Small pink, yellow, white, and lavender flower clusters |
| Clover Tufts  | Tiny clover patches around paths and fences             |
| Grass Tufts   | Clean garden grass details                              |
| Baskets       | Small woven baskets for markets and homes               |
| Apples        | Red apples for market stalls and loot props             |
| Bread Loaves  | Small bakery goods and vendor props                     |
| Books         | Closed and open books for shops, quests, and libraries  |
| Tools         | Hammer, tongs, spade, garden fork, scissors             |
| Coins         | Small gold coin stacks or loose coins                   |
| Petals        | Scattered flower petals near arches and shrines         |
| Bunting       | Colorful hanging flags for festivals and streets        |
| Rope Coil     | Useful for docks, wells, carts, and shops               |
| Candles       | Warm sacred candles for shrines and inns                |
| Soap Bottle   | Small bottle for healer, bath, or household props       |
| Folded Cloth  | Laundry, market cloth, or inn prop                      |
| Herb Bundle   | Healer or gardener ingredient                           |
| Pavers        | Loose stone chunks for path edges                       |
| Fallen Leaves | Soft green/yellow leaves near gardens                   |
| Cat Bowl      | Friendly animal detail                                  |
| Bird Seed     | Small grain pile for doves and birds                    |
| Tiny Bird     | Small peaceful bird sprite                              |
| Flower Pot    | Small decorative clay pot                               |
| Quest Paper   | Tiny note or parchment                                  |
| Wax Seal      | Red seal for letters and official documents             |
| Teacup        | Inn or home detail                                      |
| Yarn Ball     | Cozy indoor prop                                        |
| Feather       | Dove or bird detail                                     |

---

# 8. VFX / Effects

Town / Sanctuary effects should be gentle, readable, and non-threatening. They should communicate interaction, healing, guidance, crafting, and safety.

---

## 8.1 Spark Effects

### Description

Small friendly sparkles used for loot pickups, quest completion, interaction highlights, and magical comfort.

### Required Variants

1. Golden sparkle pop.
2. Blue-white twinkle.
3. Pink flower sparkle.
4. Coin glint.
5. Quest completion sparkle.
6. Blessing shimmer.

### Palette

Sun Gold, Butter Yellow, Cloud White, Soft Teal, Petal Pink.

---

## 8.2 Leaf / Dust

### Description

Small movement and environmental particles.

### Required Variants

1. Footstep dust.
2. Leaf swirl.
3. Broom sweep trail.
4. Garden rake dust.
5. Soft wind swirl.
6. Petal drift.

### Palette

Warm Stone, Honey Brown, Meadow Green, Clover Green, Petal Pink.

---

## 8.3 Light / Lantern Flash

### Description

Warm flashes and glows from lanterns, candles, holy bells, and town lights.

### Required Variants

1. Lantern glow pulse.
2. Candle flicker.
3. Bell sparkle.
4. Sunbeam glint.
5. Window light shimmer.
6. Streetlamp halo.

### Palette

Lantern Gold, Butter Yellow, Sun Gold, Cloud White.

---

## 8.4 Sanctuary Magic

### Description

Positive magic used for healing, protection, blessings, teleportation, and safe-zone effects.

### Required Variants

1. Healing pulse.
2. Blessing circle.
3. Protective bubble.
4. Sanctuary sigil glow.
5. Fountain mist.
6. Portal shimmer.
7. Dove sparkle trail.
8. Rainbow glow.
9. Mana restoration sparkle.
10. Safe-zone boundary pulse.

### Palette

Soft Teal, Sky Blue, Cloud White, Sun Gold, Lavender, Banner Blue.

---

# 9. HUD Ideas

The Town / Sanctuary HUD should communicate comfort, clarity, safety, and helpfulness. It should be more decorative than combat UI, but still readable.

---

## 9.1 Safe Zone / Friendly Area / Sanctuary Badge

### Visual Description

A badge or UI marker that clearly tells the player they are in a protected area.

### Design Notes

- Use a shield, dove, sun, flower, or sanctuary crest.
- Should feel official and friendly.
- Avoid skulls, spikes, blood, or warning colors.
- Can appear near the minimap or above the player status HUD.

### Suggested Text Variants

`SAFE ZONE`
`FRIENDLY AREA`
`SANCTUARY`
`SANCTUARY OF HOPE`
`REST • HEAL • TRADE`

### Badge Variants

#### Shield Badge

- Blue shield with gold trim.
- White dove or sun icon.
- Best for official town protection.

#### Wooden Sign Badge

- Friendly wooden sign with flowers.
- Best for entrances and shop districts.

#### Floating Magic Badge

- Circular rune badge with teal glow.
- Best for magical sanctuary boundaries.

#### Banner Badge

- Hanging blue banner with gold emblem.
- Best for UI menus, town hall, and faction areas.

### Palette

Banner Blue, Sun Gold, Cloud White, Soft Teal, Sanctuary Cream.

---

## 9.2 Suggested HUD Components

| HUD Element        | Description                                             |
| ------------------ | ------------------------------------------------------- |
| Quest Notice       | Parchment note with exclamation marker                  |
| Vendor Header      | Blue/gold shop UI header with small coin or scale icon  |
| Crafting Header    | Warm wood/gold panel with hammer, thread, or anvil icon |
| Safe Zone Badge    | Shield, dove, sun, or sanctuary crest                   |
| Friendly Area Sign | Wooden sign with flowers and readable text              |
