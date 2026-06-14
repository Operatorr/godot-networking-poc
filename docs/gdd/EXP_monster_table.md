# Equation

The monster EXP reward table uses this equation:

```text
MonsterEXP(monsterLevel) = round(100 × 1.15^(monsterLevel - 1))
```

Where:

```text
100 = base EXP for a level 1 monster
1.15 = EXP growth rate per monster level
monsterLevel = the monster's level
```

So:

```text
Level 1  = round(100 × 1.15^0)  = 100
Level 2  = round(100 × 1.15^1)  = 115
Level 10 = round(100 × 1.15^9)  = 352
Level 50 = round(100 × 1.15^49) = 94,231
Level 66 = round(100 × 1.15^65) = 881,779
```

In design terms:

```text
MonsterEXP(L) = round(BaseEXP × GrowthRate^(L - 1))
```

Recommended values:

```text
BaseEXP = 100
GrowthRate = 1.15
```

So the final equation is:

```text
MonsterEXP(L) = round(100 × 1.15^(L - 1))
```

## Table

| Monster Level | EXP Reward |
| ------------: | ---------: |
|             1 |        100 |
|             2 |        115 |
|             3 |        132 |
|             4 |        152 |
|             5 |        175 |
|             6 |        201 |
|             7 |        231 |
|             8 |        266 |
|             9 |        306 |
|            10 |        352 |
|            11 |        405 |
|            12 |        465 |
|            13 |        535 |
|            14 |        615 |
|            15 |        708 |
|            16 |        814 |
|            17 |        936 |
|            18 |      1,076 |
|            19 |      1,238 |
|            20 |      1,424 |
|            21 |      1,637 |
|            22 |      1,883 |
|            23 |      2,166 |
|            24 |      2,491 |
|            25 |      2,864 |
|            26 |      3,294 |
|            27 |      3,788 |
|            28 |      4,356 |
|            29 |      5,010 |
|            30 |      5,761 |
|            31 |      6,625 |
|            32 |      7,618 |
|            33 |      8,761 |
|            34 |     10,075 |
|            35 |     11,586 |
|            36 |     13,324 |
|            37 |     15,323 |
|            38 |     17,622 |
|            39 |     20,266 |
|            40 |     23,306 |
|            41 |     26,802 |
|            42 |     30,822 |
|            43 |     35,445 |
|            44 |     40,762 |
|            45 |     46,877 |
|            46 |     53,877 |
|            47 |     61,958 |
|            48 |     71,252 |
|            49 |     81,940 |
|            50 |     94,231 |
|            51 |    108,366 |
|            52 |    124,621 |
|            53 |    143,314 |
|            54 |    164,811 |
|            55 |    189,533 |
|            56 |    217,963 |
|            57 |    250,658 |
|            58 |    288,256 |
|            59 |    331,494 |
|            60 |    381,218 |
|            61 |    438,400 |
|            62 |    504,160 |
|            63 |    579,784 |
|            64 |    666,751 |
|            65 |    766,764 |
|            66 |    881,779 |
