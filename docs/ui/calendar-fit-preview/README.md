# Calendar fit rule

Follow-up to #491. In the wide workspace the Calendar picks its window and its team columns from the width of the rows container (`lib/fixture-board-fit.ts`, unit-tested):

1. If 2 columns of 12 gameweeks fit, use 12 (then 10, then 8) in as many columns as fit.
2. Otherwise one column with the largest window that fits (current behaviour).
3. An explicit pick of 5/8/10/12 in the selector still wins; its column count follows from the width.

Cells never stretch (78 px per gameweek, 40 px between columns).

| State at 2560 | Result | Capture |
| --- | --- | --- |
| All 3 panels open (rows container about 1,490 px) | 2 columns x 8 gameweeks (J8-J15) | [open](open-2560-calendar.png) |
| Squad collapsed (about 2,030 px) | 2 columns x 12 gameweeks (J8-J19) | [Squad collapsed](squad-collapsed-2560-calendar.png) |

Captures use a local harness with synthetic squad/chat data and the real bundled calendar; they do not validate production auth or the live backend.
