## EXP Contribution Spec Summary

EXP is awarded based on **encounter participation**, not only damage dealt and not only proximity.

A player does **not** need to damage the exact monster that died. They only need to have meaningfully contributed to the same encounter.

---

## 1. Encounter-based EXP

An **encounter** is a combat situation involving one or more monsters and one or more players in the same combat area.

Examples:

```text
Two players enter a room.
Player A fights Monster A.
Player B fights Monster B.
Both monsters are part of the same encounter.
Both players can qualify for EXP from both kills.
```

This keeps co-op play fair while still preventing passive leeching.

---

## 2. EXP eligibility rules

A player receives EXP from a monster death if all of these are true:

```text
1. The player is part of the same encounter.
2. The player is within EXP reward radius when the monster dies.
3. The player contributed recently.
4. The player contributed enough to pass the minimum contribution requirement.
```

Recommended values:

```text
EXP reward radius: 30 meters
Recent contribution window: 15 seconds
Minimum contribution required: 2% of total encounter contribution
```

So:

```text
Player contribution share =
Player contribution / Total encounter contribution
```

The player qualifies if:

```text
Player contribution share >= 0.02
```

---

## 3. EXP radius rule

A player must be within the EXP radius when the monster dies.

Recommended rule:

```text
A player must be within 30 meters of the monster death location,
or inside the same encounter zone.
```

For open-world combat, use radius.

For dungeons, rooms, caves, and boss arenas, use encounter zones instead of line-of-sight raycasts.

Recommended:

```text
Open world: 30 meter radius
Dungeon rooms: same encounter zone
Boss arenas: same boss arena
```

Do **not** require raycast line-of-sight unless you specifically want walls to block EXP. In most cases, raycasts make healer and support gameplay feel worse.

---

## 4. Contribution equation

Use a combined contribution score:

```text
Contribution =
  DamageDealt
+ EffectiveHealing × 0.50
+ ShieldingAbsorbed × 0.50
+ DamageTaken × 0.25
+ DamageMitigated × 0.50
+ BuffValue
+ DebuffValue
+ ControlValue
+ TauntValue
```

Where:

```text
EffectiveHealing = healing that actually restores missing HP
ShieldingAbsorbed = damage prevented by shields
DamageTaken = damage received from encounter monsters
DamageMitigated = damage reduced by blocks, armor skills, defensive abilities, parries, guards, etc.
```

---

## 5. Recommended contribution weights

| Action                   |                     Contribution value |
| ------------------------ | -------------------------------------: |
| Damage dealt             |                        `damage × 1.00` |
| Effective healing        |                       `healing × 0.50` |
| Shielding absorbed       |               `shielded damage × 0.50` |
| Damage taken             |                  `damage taken × 0.25` |
| Damage mitigated         |              `mitigated damage × 0.50` |
| Buffing allies           |             estimated value of benefit |
| Debuffing enemies        |             estimated value of benefit |
| Crowd control            | fixed value based on strength/duration |
| Taunting / forcing aggro |      fixed value or threat-based value |
| Reviving ally            |                      large fixed value |

---

## 6. Buff, debuff, and control values

For simple implementation, use fixed values instead of complex calculations.

Recommended examples:

```text
Minor buff: 50 contribution
Major buff: 150 contribution
Minor debuff: 50 contribution
Major debuff: 150 contribution
Interrupt: 100 contribution
Short stun/root/slow: 100 contribution
Long or important crowd control: 250 contribution
Taunt: 150 contribution
Revive: 500 contribution
```

These numbers can be tuned later.

---

## 7. Party EXP rule

Recommended party behavior:

```text
If players are in the same party and eligible:
  each eligible party member receives the monster's EXP reward.

If players are not in the same party:
  EXP can be split by contribution share, or only given to eligible participants depending on your design.
```

For your LitRPG-style game, I recommend:

```text
Eligible party members receive full monster EXP.
Nearby non-party players must qualify separately.
```

This makes co-op feel good and simple.

---

## 8. Anti-boosting rule

Being nearby is not enough.

A player receives no EXP if they are only standing near the fight but did not meaningfully contribute.

Example:

```text
Level 1 player stands near a level 60 monster kill.
They are within radius.
They did no damage, healing, shielding, tanking, support, or control.
Contribution share = 0%.
They receive 0 EXP.
```

But:

```text
Level 30 healer keeps the tank alive during a level 60 monster kill.
They are nearby.
They contributed recently.
They pass the 2% contribution threshold.
They receive EXP.
```

---

## 9. Final recommended rule text

```text
EXP is awarded to eligible encounter participants.

A player is eligible if they are within the encounter area or EXP radius, have contributed within the last 15 seconds, and contributed at least 2% of the total encounter contribution.

Contribution includes damage dealt, effective healing, shielding, damage taken, damage mitigated, buffs, debuffs, crowd control, taunts, and revives.

Players do not need to damage the exact monster that died, as long as they contributed meaningfully to the same encounter.

Players who are merely nearby but do not contribute receive no EXP.
```

This gives you fair co-op EXP, supports tanks and healers, and blocks most passive boosting.
