# i138 — MarkdownLite draws tables

**Seen 2026-10-04 in prod:** «Compara a Haaland con Cole Palmer». The model wrote a
markdown table, and the bubble showed «| Dato | Haaland | Palmer |» as raw lines.

## Change (`components/MarkdownLite.tsx`)

- **GFM table:** a header row, then a separator row **of the same width** (`---`, with
  alignment `:--` / `--:` / `:-:`), then rows until a blank line or a line without
  `|`.
- **Not tables:**
  - a line with a stray `|` and no separator below;
  - a separator of a different width;
  - `texto` followed by `---`.
- **Cell parsing:**
  - outer pipes are optional;
  - `\|` is a literal pipe;
  - short rows are padded and long rows are cut to the header width;
  - bold and italic (i126) render inside cells.
- **Lists:** an open list closes before the table, and a list after it is still a list.
- **Mobile:** the table scrolls inside its own `overflow-x-auto` wrapper. The first
  capture showed that this alone isn't enough:
  - the chat bubble is a flex item with `max-w-prose` and `min-width: auto`, so the
    table's no-wrap min-content width widened it past the screen (390px viewport);
  - fix: the wrapper sits inside a one-column `minmax(0,1fr)` grid, which contributes
    0 to min-content and its full width to max-content, so the bubble widens up to
    its cap and the table scrolls;
  - this is solved inside MarkdownLite, so it applies to every caller (bubble,
    multi-intent, web search).

## Gate

- **jest `markdown-lite.test.tsx`:** +12 table tests, including the prod case. Full UI
  suite 640/640, `tsc` 0.
- **Captures with the real component** (`MessageList` → assistant bubble → MarkdownLite)
  on a temporary page, not committed, Chromium:
  - `artifacts/i138-before-{desktop,mobile}.png`: main, raw pipes.
  - `artifacts/i138-after-{desktop,mobile}.png`: two tables (prod comparison and a
    7-column one).
  - Mobile: bubble edge at 358px on a 390px viewport, no page overflow, the wide table
    scrolls inside (`scrollWidth > clientWidth` on its wrapper).
