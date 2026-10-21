# Workspace polish review

Follow-up to #487 (wide workspace). Actual ChatShell components with synthetic API/team responses in a local browser harness (production build, Edge). The harness is not committed; captures do not validate production authentication or live backend responses.

## What changed

- Center content (messages, cards, composer) is capped at 840 px and centered; extra width goes to the side panels and margins.
- Side panels scale with the viewport: Squad `clamp(280px, 21vw, 560px)` (302 / 403 / 538 px at 1440 / 1920 / 2560), Commands `clamp(240px, 16vw, 420px)` (240 / 307 / 410 px).
- One heading per panel, inside the panel box; panel tops line up with the center panel.
- Panel toggles are the panel-left / panel-right icons (`Ocultar panel …` / `Mostrar panel …`, aria-label + tooltip), in the same position open or collapsed.
- Chat / Calendar is the brand pill switcher.
- FPL / Mundial switch is hidden behind `SHOW_SECTION_SWITCHER` (`lib/features.ts`); World Cup code, routes and backend are untouched.
- Larger type inside the workspace only; mobile sizes are unchanged.
- Calendar fills the whole center column (no cap). The window is the largest of 5/8/10/12 gameweeks that fits (12 only exists in the workspace), and team rows use as many columns as fit by width (`2 x 12 GW` needs about 1,900 px of board). Cells never stretch.
- The quota pill hides itself when the counters are missing instead of printing `NaN`.

## Captures

Name: `<state>-<width>-<chat|calendar>.png`. States: `open`, `sq` (Squad collapsed), `cmd` (Commands collapsed), `both`.

| State | 2560 Chat | 2560 Calendar | 1920 Chat | 1920 Calendar |
| --- | --- | --- | --- | --- |
| open | [Chat](open-2560-chat.png) | [Calendar](open-2560-calendar.png) | [Chat](open-1920-chat.png) | [Calendar](open-1920-calendar.png) |
| Squad collapsed | [Chat](sq-2560-chat.png) | [Calendar](sq-2560-calendar.png) | [Chat](sq-1920-chat.png) | [Calendar](sq-1920-calendar.png) |
| Commands collapsed | [Chat](cmd-2560-chat.png) | [Calendar](cmd-2560-calendar.png) | [Chat](cmd-1920-chat.png) | [Calendar](cmd-1920-calendar.png) |
| Both collapsed | [Chat](both-2560-chat.png) | [Calendar](both-2560-calendar.png) | [Chat](both-1920-chat.png) | [Calendar](both-1920-calendar.png) |

Also: [1440 Chat](open-1440-chat.png) · [1440 Calendar](open-1440-calendar.png) · [390 Chat (mobile, unchanged)](open-390-chat.png).

## Validation

- Jest (in band): all suites passed, including the workspace integration tests (only the collapse button names changed) and a new test for the quota pill with missing data.
- `next build` (type check included) passed.
- Without `--runInBand`, several suites die from worker out-of-memory on this machine; those are not test failures. CI is the reference.
