# Does this make sense? Ten players, before the match and what happened (2026-10-11)

For each player: what the models said **using only matches before the gameweek-6 fixture**, and what
happened in that fixture. Please mark the last column: **yes**, **no** (and what you expected), or **?**.
Names only here; the aggregate report has numbers and no names.

How to read the third column of the prediction, `start chance / expected minutes / role`:

- *start chance*: the model's probability that he starts (the "form" signal; it assumes everybody is fit,
  because who was injured at the time is not known to it);
- *expected minutes*: minutes if he plays, weighted by how often he starts or comes on;
- *role*: the tactical role his last starts imply, with the side for full-backs and wingers.

The "case" says why he is in the table: a fixed starter, a rotation player at a club with European
matches, a player the role model flags as out of position against his FPL position, a newcomer to the
squad, a player in your team (entry 68643, gameweek 6), or a large miss of the start chance.

| player | club | case | before the match: start chance / expected minutes / role | what happened | makes sense? |
|---|---|---|---|---|---|
| Kristoffer Ajer | Brentford | fixed starter | 92% / 83 min / center_back | started, 90 min, Centre Back |  |
| Matty Cash | Aston Villa | rotation european club | 39% / 40 min / full_back (right) | started, 90 min, Right Back |  |
| Thomas Meunier | Sunderland | out of position | 84% / 67 min / winger (right) | started, 34 min, Right Midfield |  |
| Nicolas Jackson | Aston Villa | newcomer | 86% / 63 min / forward | started, 90 min, Attacker |  |
| Pascal Groß | Brighton & Hove Albion | leo team | 84% / 75 min / central_midfield | started, 90 min, Central Midfield |  |
| Daniel Ballard | Sunderland | large miss | 84% / 75 min / — | did not play |  |
| Keane Lewis-Potter | Brentford | fixed starter | 92% / 76 min / full_back (left) | started, 67 min, Attacking Midfield |  |
| Zion Suzuki | Aston Villa | rotation european club | 78% / 70 min / goalkeeper | started, 90 min, Goalkeeper |  |
| Maxim De Cuyper | Brighton & Hove Albion | out of position | 84% / 71 min / winger (left) | started, 68 min, Left Midfield |  |
| José María Andrés Baixauli | Brighton & Hove Albion | newcomer | 34% / 35 min / — | started, 90 min, Central Midfield |  |

Three things to look at in particular:

- **Thomas Meunier and Maxim De Cuyper** are listed by FPL as defenders; the provider labels them Right
  and Left Midfield, and the role model (decision of 2026-10-11) calls that "winger", so it flags them as
  half out of position. Are they, in your eyes, wing-backs?
- **Keane Lewis-Potter** was expected as a left full-back and played attacking midfield: is that a real
  change of role?
- **Daniel Ballard** was a near-certain starter on form and did not play at all: injured or dropped?
