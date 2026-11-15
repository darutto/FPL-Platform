# Wide workspace review

Actual ChatShell components with synthetic API/team responses in a local browser harness. Authentication and Next navigation are stubbed only in the untracked harness; these captures do not validate production authentication or live backend responses. Captured with Chromium at CSS viewport widths below (desktop height 1080, mobile height 844).

## Layout

- 1440+: Squad, Chat/Calendar, Commands visible together.
- 1280–1439: Squad collapsed by default; Commands visible.
- Below 1280: existing pager and touch behavior.
- Side widths: 280/200 at 1440, 320/240 from 1600, 360/280 from 2200.
- Chat prose at most 720 px; structured cards and Calendar use the available center.
- Explicit collapse choices persist locally. Hidden panels stay mounted to retain conversation, draft, scroll and selection.

| Width | Chat | Calendar |
| --- | --- | --- |
| 2560 | [Chat](chat-2560.png) | [Calendar](calendar-2560.png) |
| 1920 | [Chat](chat-1920.png) | [Calendar](calendar-1920.png) |
| 1440 | [Chat](chat-1440.png) | [Calendar](calendar-1440.png) |
| 1280 | [Chat](chat-1280.png) | [Calendar](calendar-1280.png) |
| 390 | [Chat](chat-390.png) | [Calendar](calendar-390.png) |

[Collapsed Squad](collapsed-1920.png) · [Disconnected Squad](disconnected-1440.png)

## Rich cards

| Card | Wide | Mobile |
| --- | --- | --- |
| Ranking/table | [2560](table-2560.png) | [390](table-390.png) |
| Comparison | [2560](compare-2560.png) | [390](compare-390.png) |
| Player with mini-pitch | [2560](pitch-2560.png) | [390](pitch-390.png) |
| Defensive zones | [2560](zones-2560.png) | [390](zones-390.png) |

## Validation

- Frontend Jest: 58 suites, 776 tests and 3 snapshots passed, before the final Squad action addition. The affected suites then passed all 9 tests, including five workspace integration tests.
- TypeScript: `npx tsc --noEmit` passed.
- [31 browser checks](results.json): left-aligned card verdicts; responsive geometry; non-zero conversation scroll, draft and DOM preservation on tab changes at all five widths; Calendar/Commands switching to Chat with response; persisted collapse; disconnected Squad; no runtime errors.
- [8 rich-card checks](rich-cards-results.json): no page overflow or runtime errors at 390 and 2560.
- Existing gesture regression tests remain green. No physical-device pinch-zoom certification is claimed by these desktop Chromium captures.
- New Jest cases cover breakpoint defaults, explicit collapse persistence, resize without conversation remount, completed Calendar/Commands questions, and argument-requiring commands inserting a draft without premature submission.

Screenshots were shown to Leo before opening the PR. No merge or auto-merge is authorized.

Review adjustments: restored pre-existing UI copy from main, aligned card verdict prose to the left, and made Squad Ask AI send directly. [Squad browser check](squad-action-result.json) confirms selection stays on Calendar and Ask AI opens Chat with one answer; Jest verifies exactly one API call. Updated captures reflect the restored text and alignment.
