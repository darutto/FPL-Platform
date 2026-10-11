# Grid check for Leo — who plays on which side? (2026-10-11)

> **Superseded for Liverpool-City (2026-10-11, later).** That table was built before the match was played,
> from provisional lineups, and did not match Sofascore. The corrected sides are in
> [provisional lineups](2026-10-11-provisional-lineups.md). The Arsenal-Leeds table (a finished match) stands
> and was confirmed by Leo.

No payloads: just the starters of three recent Premier League matches, the provider's grid cell (`formation_field = row:col`), and the **side I infer** from it. Please confirm or correct the side for each player you know. A row marked ✗ by you is worth more than ten ✓.

How the side is inferred: row 1 is the goalkeeper; within a row, `col` is counted along the touchline and is the same physical side for both teams, so for the **home** team col 1 is its right and the highest col its left, and for the **away** team the numbering is mirrored (col 1 = its left). The last column is the provider's own detailed position for that starter, shown as a cross-check (it is not used to compute the side).

Automatic cross-check already run: over GW1–GW6 (59 matches), every starter that the provider labels Right Back, Left Back, Right Midfield or Left Midfield (420 of 420) sits in the cell this rule predicts. What it cannot check is a player's real side when the provider's label is central — that is what this table is for.

## Arsenal vs Leeds United — 2026-10-10

**Arsenal** — home, formation 4-2-3-1

| field | player | inferred side | provider position |
|---|---|---|---|
| 1:1 | David Raya | — | Goalkeeper |
| 2:1 | Ben White | right | Right Back |
| 2:2 | Ezri Konsa | centre-right | Centre Back |
| 2:3 | Gabriel | centre-left | Centre Back |
| 2:4 | Riccardo Calafiori | left | Left Back |
| 3:1 | Declan Rice | right | Central Midfield |
| 3:2 | Myles Anthony Lewis-Skelly | left | Central Midfield |
| 4:1 | Bukayo Saka | right | Right Midfield |
| 4:2 | Martin Ødegaard | centre | Attacking Midfield |
| 4:3 | Noni Madueke | left | Left Midfield |
| 5:1 | Kai Havertz | centre | Attacker |

## Liverpool vs Manchester City — 2026-10-11

**Liverpool** — home, formation 4-2-3-1

| field | player | inferred side | provider position |
|---|---|---|---|
| 1:1 | Alisson | — | Goalkeeper |
| 2:1 | Ronald Araujo | right | Right Back |
| 2:2 | Virgil van Dijk | centre-right | Centre Back |
| 2:3 | Jérémy Jacquet | centre-left | Centre Back |
| 2:4 | Milos Kerkez | left | Left Back |
| 3:1 | Alexis Mac Allister | right | Central Midfield |
| 3:2 | Ryan Gravenberch | left | Central Midfield |
| 4:1 | Víctor Muñoz | right | Right Midfield |
| 4:2 | Dominik Szoboszlai | centre | Attacking Midfield |
| 4:3 | Bradley Barcola | left | Left Midfield |
| 5:1 | Florian Wirtz | centre | Attacker |

**Manchester City** — away, formation 4-2-3-1

| field | player | inferred side | provider position |
|---|---|---|---|
| 1:1 | Gianluigi Donnarumma | — | Goalkeeper |
| 2:1 | Josko Gvardiol | left | Left Back |
| 2:2 | Marc Guéhi | centre-left | Centre Back |
| 2:3 | Rúben Dias | centre-right | Centre Back |
| 2:4 | Matheus Nunes | right | Right Back |
| 3:1 | Elliot Anderson | left | Central Midfield |
| 3:2 | Enzo Fernández | right | Central Midfield |
| 4:1 | Jérémy Doku | left | Left Midfield |
| 4:2 | Rayan Cherki | centre | Attacking Midfield |
| 4:3 | Antoine Semenyo | right | Right Midfield |
| 5:1 | Erling Haaland | centre | Attacker |

## Manchester City at home — 2026-09-20

**Manchester City** — home, formation 4-2-3-1

| field | player | inferred side | provider position |
|---|---|---|---|
| 1:1 | Gianluigi Donnarumma | — | Goalkeeper |
| 2:1 | Matheus Nunes | right | Right Back |
| 2:2 | Rúben Dias | centre-right | Centre Back |
| 2:3 | Marc Guéhi | centre-left | Centre Back |
| 2:4 | Josko Gvardiol | left | Left Back |
| 3:1 | Enzo Fernández | right | Central Midfield |
| 3:2 | Elliot Anderson | left | Central Midfield |
| 4:1 | Iliman Ndiaye | right | Right Midfield |
| 4:2 | Rayan Cherki | centre | Attacking Midfield |
| 4:3 | Antoine Semenyo | left | Left Midfield |
| 5:1 | Erling Haaland | centre | Attacker |


**Reply format:** list any wrong lines as `player: actual side`, or say "all correct".
