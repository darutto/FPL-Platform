# English version: admin walkthrough (gate "Public EN")

The checklist an admin walks through in English before `LOCALE_ROLLOUT` moves from `'admin'` to `'public'` (`packages/fpl-ui/lib/features.ts`). It lists what each screen must show and what is still Spanish on purpose, so a leftover is either a bug or a line in section 3, never a surprise.

Wording rules live in `docs/i18n-glossary.md` (British spelling, chip names in English, positive framing, no urgency words).

## 0. Before you start

- Sign in with an **admin** Clerk account. Only admins see the language pill (`Español | English`, top bar, aria name "Language") and get the browser-language default; everyone else is pinned to Spanish while the rollout is `'admin'`.
- Choose **English** in the pill. It writes the `bf_locale` cookie; reload once and check the tab title reads "FPL Assistant" and `<html lang="en">`.
- Use a real connected team ID for the squad flows, and one run where no team is connected (the "not connected" lines differ).
- Do **three passes**: desktop wide (workspace with squad and commands panels), narrow/mobile (swipe pager), and keyboard/screen-reader names (section 2, last column).
- Switch back to Español at the end and confirm nothing English leaked into the Spanish view.

How to judge a line: English, British spelling, no Spanish word anywhere (player and team names, Patreon tier names, `BF`, `FDR`, `xG`, `GW`, prices as `£x.xm` are allowed to stay as they are).

## 1. Flows

Each row says what to do, then what must be on screen. "Free text" prompts are answered by the LLM orchestrator, so wording of the prose varies; check **language and framing**, not exact sentences.

| # | Flow | Do | Must see in English |
|---|------|----|---------------------|
| 1 | **Login / post-login** | Open `/login` signed out; sign in; watch `/post-login`. | Title "FPL Assistant", "Sign in with your Patreon account to access the chat.", then "Checking your Patreon membership...". The Clerk sign-in widget is Clerk's own text (see section 3). Lands on `/chat`. |
| 2 | **Empty chat + starters** | Open `/chat` with no history. | "Ask a question about your Fantasy Premier League team." Six chips: "Who should I captain?", "Should I use the Triple Captain?", `/differentials under 10%`, `/compare …`, `/transfer … for …`, `/fixtures …` (names are the current top buys/sells, or Haaland / Bruno Fernandes / Cole Palmer / Saka when the feed is empty). Tapping a chip sends it immediately. Input placeholder and the send / web-search buttons read in English. |
| 3 | **Slash menu** | Type `/`. | Menu named "Slash commands": `/captain`, `/compare`, `/transfer`, `/fixtures`, `/differentials`, `/chips`, `/rankings` with English labels and "e.g. …" hints. Typing a Spanish prefix (`/capi`) still finds the command. |
| 4 | **Captain** | "Who should I captain?" and `/captain Haaland`. | Captain card: "Captain score", tiers **Favourite / Upside / Differential / Not this week** (the last one was "Avoid"; see section 3 for the backend text that still says "Evitar"). Prose in English, framed as an opportunity. |
| 5 | **Captain candidates (ranking)** | `/rankings` or "top captains this week". | Title "Captain candidates"; sections "A) Candidates from your squad" / "B) Best candidates overall"; "YOURS" badge; "Differential pick … owned by n%" or "No differential pick this gameweek…"; "Worth knowing". Without a team: "No team connected; showing the overall ranking only." |
| 6 | **Compare** | `/compare Haaland vs Bruno Fernandes`; also the chip wizard (type `/compare`, pick player A then B). | "Comparison", "Player A / Player B", "Pick", Home / Away, margin ("Narrow / Moderate / Clear margin"), "The best pick is …" or "Too close to call.", "… leads by n pts". Ambiguous name: "Which of these players did you mean?", "First player:", "Cannot see your player? Type the name below." |
| 7 | **Transfer** | `/transfer Cole Palmer for Saka`; and one over-budget case. | Card "Transfer", "← Out", verdict "The best pick is …" / "… is a marginal upgrade." / "Holding is the right read.", "Keep", "Make the transfer on FPL"; warnings "Exceeds your available budget", "Using an extra transfer will cost −4 points". No "buy / sell / urgent" wording anywhere (the glossary says "bring in"). |
| 8 | **Chips** | `/chips Triple Captain`, "should I use my Bench Boost?". | Chip names stay **Wildcard, Bench Boost, Free Hit, Triple Captain** (never translated, also in model prose). Window and recommendation lines in English. |
| 9 | **Differentials** | `/differentials under 10%`. | Title "Differentials", "<n% owned", columns Player / Own / Price, the BF-score disclaimer in English. The threshold is honoured: the list header reads "ownership < 10%" (verified offline 2026-10-28). |
| 10 | **Fixtures / calendar** | Calendar tab (or panel) and `/fixtures Haaland`. | Heading "Fixtures"; two difficulty axes "Attack difficulty / Defence difficulty"; `GW7` (not `J7`) everywhere; venue H/A (not L/V); band words, run labels, legend, "double gameweek", competition names; view and navigation controls in English; the data note. Tap a team row and a cell: the question that lands in the chat is English and names team, opponent, venue and gameweek (contract in `fixture-question-contract.test.ts`). |
| 11 | **Zones ("Where to attack")** | Open a team's zones card and a player's zones section; open the squad pitch zones. | "Where to attack", zone pills and lateral labels in English, no "weakness" wording, exploiter lines in English, positions as GKP/DEF/MID/FWD. The verdict sentence and provenance label come from the backend and may still be Spanish (section 3). |
| 12 | **Squad** | Connect a team ID; tap a player; disconnect. | Squad pitch with GW stats, "Bench", tap hints, detail panel; connect form "FPL team ID" / "Connect" / "Connecting…" / "Disconnect"; errors "Team not found. Check the ID.", "Invalid team ID — it must be a positive number.", "Could not reach the FPL API. Please try again." |
| 13 | **Subscribe** | Open `/subscribe`. | "Choose your membership"; five cards with Patreon names plus an English descriptor: Tribuna · Supporter, Gafete de cancha · Pitch Pass, Socio Junior · Junior Member, Ejecutivo: carné de plata · Executive: Silver Card, Ejecutivo: Carné de oro · Executive: Gold Card; "Recommended", "Assistant usage", "Join", perks and "n messages a day" lines in English; every card still links to Patreon. |
| 14 | **Quota / upgrade** | Open the quota indicator; use up the daily messages with a free account (or the dev tier switcher, which stays Spanish). | "Message quota", "Today / This month", "n msgs left", "Current tier:", "Includes web search", "Upgrade on Patreon". At the wall, the upgrade prompt appears. Its sentence is written by the backend (section 3). |
| 15 | **Web search & sources** | Turn on the globe toggle (premium tier) and ask something external. | Locked tooltip "Web search (premium feature)"; card "Web search" with badge "Web search · AI · unverified information"; "Sources consulted". |
| 16 | **Share** | Share an answer. | Button "Share card"; statuses "Card downloaded and text copied." / "Text copied."; shared card says "Club Bendito Fantasy" and "Try it yourself at Club Bendito Fantasy." |
| 17 | **Errors and edges** | Kill the network mid-answer; wait for a session to expire; hit a nonsense URL. | "Session expired. Start a new conversation.", "Session limit reached — please try again in a few minutes"; the chat's generic error is English. A nonsense URL shows Next.js's own English 404 (no custom 404 page exists). |

## 2. Accessible names (third pass)

With a screen reader or the accessibility tree, these must be English, not only visible text: the chat input ("Ask the FPL assistant"), send, web-search toggle (three states), slash menu, quota close, workspace toolbar ("Workspace navigation"), panel toggles ("Hide Squad panel", "Show Commands panel"), pager edge hints ("Go to Fixtures"), the fixtures navigation and the cell tooltips, zone and squad pitch labels, share button, tables inside answers (region "Table"), language pill ("Language").

## 3. Still Spanish on purpose (or not yet), and why

Intentional, not bugs:

- **World Cup section** (`/wc`, `WcChatShell`, `components/wc/*`, `lib/wc-slash-commands.ts`): the tournament is over and the section switcher is hidden (`SHOW_SECTION_SWITCHER` off). It stays Spanish; its switcher labels are translated in case it comes back.
- **Dev tier switcher** (`components/dev/DevTierSwitcher.tsx`): developer tool, not user-facing.
- **Patreon tier names** (Tribuna, Gafete de cancha, Socio Junior, Ejecutivo…) stay as Patreon spells them; English adds a descriptor after them.
- **Spanish slash registry** (`SLASH_COMMANDS`) is the Spanish source of truth; the English names are layered on top, and both spellings are accepted everywhere.
- **Injury table column matcher** lists Spanish and English keywords so either phrasing of a column resolves; not display text.
- **Share-image error** ("No se pudo generar la imagen de la tarjeta.") is thrown and swallowed; it never reaches the screen.
- **Fixture mock** (`lib/fixture-outlook-mock.ts`) is used by tests only.
- **Clerk widget** on `/login` is Clerk's own copy (the app sets no Clerk localisation, so it is English for every user, Spanish included).
- **No custom 404 or error pages** exist; Next.js defaults are shown.

Not done yet, owned elsewhere (check these in the walkthrough and log what you see):

- **Backend zonal text (S5)**: verdict, weakness label, provenance label and club note come from the backend and are not locale-aware. Team verdicts are recognised by the client and shown in English; anything else passes through in Spanish.
- **Backend upgrade prompt on quota exhaustion** lists plans by their Spanish display name without the English descriptor.
- **Backend captain tier text** (`captain_tiers.py`, grounded-assistant renderer/catalogue) still says "Evitar" in prose and tables the backend writes; only the UI badge was softened to "Not this week" / "No esta semana".
- **Differentials threshold**: `under N` / `menos del N%` is honoured in both languages (checked offline 2026-10-28; the default is 15%). A bare positional number (`/differentials 10`) is not read as a threshold and falls back to 15%. The list header and rows come out in English even in a Spanish turn (existing backend text, not locale-aware).
- **Free-text routing in English** is unmeasured. The two free-text starters and the fixture tap questions go to the LLM orchestrator, and the deterministic `route()` fallback mishandles tap questions in both languages. The paid English battery (S7) is what measures this; the chips with a slash (`/compare`, `/transfer`, `/fixtures`, `/differentials`) are parsed by the backend prompt registry and verified offline to resolve to the same prompts as their Spanish twins.

## 4. Sign-off

Public EN opens when: every row in section 1 passes in all three passes; every English-visible leftover is either listed in section 3 or fixed; the Spanish pass at the end is unchanged; and the S7 battery has been run and read. Record the date, the account used, and anything found next to this file's PR.
