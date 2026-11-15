# Calendar fluid sizing

Follow-up to #491 / #493. Real `FixturesBoard` inside the real `ChatShell`, with the bundled season calendar and a synthetic squad, rendered from a production build in Edge. Captures do not validate production auth or the live backend.

## What changed (wide workspace only; the pager and mobile keep their sizes)

- **Compact grows with its panel.** Cell, row height and type are fluid between the old fixed size and a maximum, from the board's own width (container query units): cell `clamp(54px, fit, 92px)`, row `clamp(24px, 0.4 x cell, 36px)` and also limited by the viewport height so the 20 rows fit, opponent `12 -> 17px`, venue `8.5 -> 11px`, gameweek `11 -> 12.5px`, team code `13 -> 18px`. At the maximum the glyphs equal Detailed's, so switching views keeps one type scale. The 92 px cap is deliberate: beyond it a chip becomes a banner; with panels collapsed the table simply does not fill the panel (decision: keep the cap).
- **Compact picks its own window**: the largest of 5/8/10/12 gameweeks whose cells stay at least 62 px (`fitCompactWindow`). It is one table, never split in columns. Detailed keeps the #493 rule (2 x 8 at 2560 with three panels). A manual pick of the window still wins for the session; there is no "Auto" button.
- **One-line header in Compact**: title, axis, window, the FDR legend and a note icon share one line (it wraps only when the panel is too narrow). The data note is not dropped: the icon's tooltip carries the warning (or the provenance line) and a click opens the same provenance stamp, warning and footer inline. Detailed and Tendencia keep their full block.
- **Ranks and reading order**: every view shows the team's place (1-20, muted, next to the code). Detailed and Tendencia fill their columns top to bottom (left column 1-10, right 11-20; with 3+ columns, equal heights). The sort itself is unchanged.
- **Sticky header row** in Compact: the table never scrolls sideways in the workspace, so the gameweek row sticks to the top of the board's own scroller.

## Measured (rendered, viewport width x height)

| Viewport | Compact window | Cell (w x h) | Vertical scroll | Detailed |
| --- | --- | --- | --- | --- |
| 2560 x 1180, 3 panels | 12 GW | 92 x 36 | none: all 20 rows fit | 2 columns x 8 GW |
| 2560 x 1180, Squad collapsed | 12 GW | 92 x 36 | none | 2 columns x 12 GW |
| 1920 x 1000 | 12 GW | 79 x 29 | none | 1 x 12 |
| 1440 x 900 | 10 GW | 65 x 24 | 57 px (rows cannot go below 24 px) | 1 x 8 |
| 390 x 844 (pager) | 8 GW | 54 x 24 (unchanged) | as before | n/a |

## Captures

| | Compact | Detailed |
| --- | --- | --- |
| 2560, three panels open | [compact-2560](compact-2560.png) | [detailed-2560](detailed-2560.png) |
| 2560, Squad collapsed | [compact-2560-squad-collapsed](compact-2560-squad-collapsed.png) | |
| 1920 | [compact-1920](compact-1920.png) | [detailed-1920](detailed-1920.png) |
| 1440 | [compact-1440](compact-1440.png) | [detailed-1440](detailed-1440.png) |
| 390 (mobile, unchanged) | [mobile-390-compact](mobile-390-compact.png) | |

## Validation

- New unit tests for the Compact fit (`fixture-board-fit.test.ts`) and a board suite (`fixtures-board-fluid.test.tsx`): window follows the width and an explicit pick wins; ranks 1-20 in Detailed, Compact and Tendencia and none in the in-chat card; rows per column = ceil(20 / columns) and the stylesheet fills by columns; the one-line Compact header with its note reachable (tooltip and inline panel); Detailed keeps its block; mobile unchanged (base tokens are the old sizes, everything fluid/sticky/viewport-sized lives under `.wide-workspace`, the rank is hidden by default, 5/8/10 selector and 8-gameweek default outside the workspace).
- jsdom has no layout, so the widths are injected where the board measures them and the stylesheet is checked as text; the measurements above come from the rendered pages.
