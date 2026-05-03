# Unhandled Intents Catalog

Prompts from beta users that fall outside the app's strict intent coverage and trigger a deterministic fallback or refusal. Each entry captures the raw input, the app's response behavior, and the underlying user need.

---

## Infrastructure / Provider Issues

### Gemini provider failing silently on every request (prod)
- **Observed:** Every POST /ask call during catalog_runner scan returned `provider_call_failure` for `gemini-2.5-flash` in Railway logs, with ~130–180ms latency and 1 attempt. Requests still returned HTTP 200.
- **Impact:** All LLM-enhanced responses fell back to deterministic-only output during the scan. Any response that requires LLM presentation (e.g. nuanced captain advice) was silently degraded without the user knowing.
- **Priority:** P1 — production reliability bug; silent degradation is worse than a visible error.
- **Source:** Railway backend logs observed 2026-05-02 during automated catalog_runner probe.
- **Notes:** Likely cause: Gemini API key quota/rate-limit hit from rapid sequential requests, or key expired. The `provider_call_failure` event fires with `attempts=1` — retry logic may not be kicking in. Check `GOOGLE_API_KEY` validity and whether the provider retry policy covers quota errors.

---

## How to use this file

When a new case arrives (screenshot or copy-paste):

1. Add an entry under the appropriate category (or create a new one).
2. Fill in the fields that are known; leave others blank for now.
3. Tag the entry with a **Priority** so future triage is easier.

Priority scale:
- `P1` — Core FPL decision, asked repeatedly, should be handled
- `P2` — Legitimate FPL question, edge case or niche
- `P3` — Out of scope for MVP, may be considered later

---

## Entry template

```
### [Short label]
- **Raw prompt:** "..."
- **App response:** [blocked / fallback / wrong intent matched / silent fail]
- **User need:** What the user actually wanted
- **Priority:** P1 / P2 / P3
- **Source:** beta tester / session date / screenshot ref
- **Notes:** Any relevant context (GW, squad state, chip active, etc.)
```

---

## Category: Transfer Planning
### Budget-constrained buy (can I afford X without selling?)
- **Raw prompt:** "tengo que meter a palmer o vendo a alguien para cuadrar el presupuesto?"
- **App response:** Blocked — transfer_advice did not fire despite clear buy-target (Palmer) and budget reasoning
- **User need:** User wanted to know if they can afford Palmer or must first sell a player to free budget
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** transfer_advice SHOULD catch this; lacks explicit 'sell X' structure but buy target is named

### NAME_BUG — Spanish 'tengo a X' absorbed into player name
- **Raw prompt:** "tengo a saka y rashford en mi equipo, a cual vendo primero?"
- **App response:** Wrong intent matched (compare_players, correct) but name extraction failed — lookup key was 'tengo a saka' not 'saka'
- **User need:** User wanted to know which of Saka or Rashford to prioritise selling
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Strip 'tengo a ' prefix before player resolution; same root as 'compara a X' bug

### Budget reserve planning for double gameweek
- **Raw prompt:** "cuanto debo tener en banco para la proxima doble jornada?"
- **App response:** Blocked — no intent covers budget reserve or double-GW planning
- **User need:** User wanted guidance on how much ITB to hold ahead of a double gameweek
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Partially related to chip_advice but no intent models budget-reserve decisions

### End-of-season transfer hit decision
- **Raw prompt:** "me quedan 3 jornadas, hago hit o aguanto con el equipo que tengo?"
- **App response:** Blocked — transfer_advice covers sell/buy pairs but not the meta-decision of whether to take a points hit
- **User need:** User wanted advice on whether a -4 transfer hit is worthwhile with 3 GWs remaining
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** No intent models cost-benefit of point deductions

### Budget picks under £5m currently in form
- **Raw prompt:** "que jugadores baratos por debajo de 5 millones estan rindiendo bien ahora mismo?"
- **App response:** Blocked — differential_picks is ownership-filtered, not price-filtered; no price+form ranking intent exists
- **User need:** User wanted a ranked list of affordable sub-£5m players currently performing well
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** High-value gap; price-filtered form ranking is a very common FPL need

### Named swap transfer — should be handled
- **Raw prompt:** "¿debería vender a Saka y fichar a Palmer?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Named swap transfer — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Transfer hit (-4) evaluation — no specific swap in mind
- **Raw prompt:** "¿vale la pena hacer un hit esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Transfer hit (-4) evaluation — no specific swap in mind
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Free transfer banking decision
- **Raw prompt:** "¿debería guardar mi transferencia libre para la próxima semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Free transfer banking decision
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Transfer-out recommendation without a target named
- **Raw prompt:** "¿a quién debería sacar de mi equipo esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Transfer-out recommendation without a target named
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Budget-constrained transfer planning
- **Raw prompt:** "tengo 1.5 millones en banco, ¿qué puedo hacer?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Budget-constrained transfer planning
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Season-end asset targeting
- **Raw prompt:** "¿a quién debería tener de cara al final de temporada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Season-end asset targeting
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Multi-intent: transfer + chip in one question
- **Raw prompt:** "¿debería hacer una transferencia y usar el wildcard esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Multi-intent: transfer + chip in one question
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


<!-- Add entries here for questions about transfers, budget, free transfers, etc. -->

---

## Category: Captain / Vice-Captain
### Two named players, user asking who to captain
- **Raw prompt:** "a quien le doy la banda si tengo a Haaland y Mbeumo como opciones?"
- **App response:** Blocked — should have been caught by rank_candidates or captain_score; names two players and asks for captain pick explicitly
- **User need:** User wanted a recommendation on which of two specific players to captain this week
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** rank_candidates or captain_score SHOULD have caught this — maps squarely to supported intents

### VC recommendation given a chosen captain
- **Raw prompt:** "a quien pongo de vicecapitan si mi capitan es Haaland?"
- **App response:** Blocked — no intent models vice-captain recommendations
- **User need:** User wanted a VC recommendation conditioned on having already chosen Haaland
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** rank_candidates could serve this by listing alternatives to Haaland; no VC-specific intent exists

### Armband chain mechanic when captain doesn't play
- **Raw prompt:** "si capianto a Salah y no juega, se le pasa la banda a alguien automaticamente?"
- **App response:** Blocked — no intent covers FPL game-rules explanations
- **User need:** User wanted to know whether the VC automatically gets the armband if the captain doesn't play
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Requires a rules/FAQ intent; Salah mention is incidental, the real question is the VC fallback rule

### Captain fixture-timing risk (late fixture)
- **Raw prompt:** "tengo a Salah como capitan pero juega el domingo, me arriesgo o cambio a uno que juega antes?"
- **App response:** Blocked — no intent combines captain value with fixture scheduling risk
- **User need:** User wanted advice on whether to keep a late-fixture captain or switch to an earlier-fixture option
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Involves captain_score + player_fixture_run signals combined; neither intent handles the timing risk angle alone

### Differential captain to chase mini-league rivals
- **Raw prompt:** "vale la pena capitar a un diferencial esta semana si quiero subir en mi liga?"
- **App response:** Blocked — no intent handles mini-league rank-gap reasoning or differential captain strategy
- **User need:** User wanted strategic advice on whether a low-ownership captain pick is worthwhile to gain mini-league rank
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Overlaps rank_candidates + differential_picks but mini-league context is not modelled by either

### Generic captaincy ranking — should be handled
- **Raw prompt:** "¿a quién debería capitar esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Generic captaincy ranking — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Explicit ranking ask — should be handled
- **Raw prompt:** "dame el ranking de capitanes para esta jornada"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Explicit ranking ask — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Named captain score — should be handled
- **Raw prompt:** "¿debería capitar a Haaland?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Named captain score — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Direct comparison — should be handled
- **Raw prompt:** "compara a Salah y Haaland"
- **App response:** supported but response too thin (< {THIN_RESPONSE_CHARS} chars)
- **App final_text:** "No player found matching 'a Salah'."
- **User need:** Direct comparison — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`compare_players` outcome=`not_found`

### Vice-captain specific recommendation — distinct from captain
- **Raw prompt:** "¿quién debería ser mi vicecapitán?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Vice-captain specific recommendation — distinct from captain
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Conditional captain fallback planning
- **Raw prompt:** "si capianto a Salah y no juega, ¿quién es la mejor alternativa?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Conditional captain fallback planning
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Differential captain — low-owned captain pick
- **Raw prompt:** "¿qué capitán diferencial me recomiendas esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Differential captain — low-owned captain pick
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Multi-intent: fixture run + captain assessment
- **Raw prompt:** "dame los fixtures de Salah y dime si es buen capitán"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Multi-intent: fixture run + captain assessment
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Multi-intent: fixture comparison + captain decision
- **Raw prompt:** "¿quién tiene mejor fixture, Salah o Mbeumo, y a quién capianto?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Multi-intent: fixture comparison + captain decision
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


### Head-to-head captaincy comparison (two named players)
- **Raw prompt:** "compara a haaland con cherki en capitania esta semana"
- **App response:** Error — "Não encontrei nenhum jogador com o nome 'a haaland'." (player not found)
- **User need:** Side-by-side captaincy assessment of Haaland vs Cherki for the current GW — fixture, form, expected points, and a recommendation.
- **Priority:** P1
- **Source:** Beta tester, 2026-04-30
- **Notes:** Two distinct failures compounding:
  1. **Name extraction bug** — Spanish preposition "a" (used before direct objects of persons: "compara *a* Haaland") was absorbed into the player name token, producing "a haaland" instead of "haaland". Parser needs to strip leading Spanish prepositions (a, al, de, del, los, las) before name lookup.
  2. **Missing multi-player intent** — even with correct name extraction, the app has no handler for comparing two players in a captaincy context. This is a very natural ask and probably the second most common captaincy question after "who should I captain?".
  3. **Language bug** — error message returned in Portuguese despite the app being Spanish-first. Likely a fallback string that was never localized.

---

## Category: Chip Strategy
### Wildcard timing relative to a double gameweek
- **Raw prompt:** "deberia usar el wildcard antes o despues de la doble jornada?"
- **App response:** Blocked — chip_advice SHOULD have caught this; timing/sequencing phrasing not recognised
- **User need:** User wanted strategic guidance on activating wildcard before vs after a double GW
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** chip_advice exists but apparently requires 'activate now' framing; timing questions are not routed

### Bench boost value with thin squad availability
- **Raw prompt:** "tiene sentido activar el bench boost en una jornada donde tengo solo 10 jugadores disponibles?"
- **App response:** Blocked — chip_advice SHOULD have caught this; conditional phrasing ('tiene sentido si...') prevented routing
- **User need:** User wanted to know if bench boost is advisable when only 10 squad players are available
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** bench_boost is a supported chip; fix: chip_advice must handle availability-conditioned framing

### Chip sequencing after wildcard is spent
- **Raw prompt:** "ya use el wildcard, que chip me queda mas rentable para el final?"
- **App response:** Blocked — chip_advice SHOULD handle this; 'ya use' (already used) state context prevented routing
- **User need:** User wanted to know which remaining chip (BB/TC/FH) offers the best end-of-season value
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** chip_advice must handle questions conditioned on a chip already being spent

### Chip stacking rules (TC + BB same GW?)
- **Raw prompt:** "puedo usar el triple capitan y el bench boost en la misma jornada?"
- **App response:** Blocked — FPL rules question; no intent covers game-rules explanations
- **User need:** User wanted to know whether TC and BB chips can be activated in the same gameweek
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Rules/FAQ intent needed; chip_advice is for personal chip decisions, not game mechanics

### Wildcard chip — should be handled
- **Raw prompt:** "¿debería usar el wildcard esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Wildcard chip — should be handled
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Timing advice for TC chip — not a yes/no this GW
- **Raw prompt:** "¿cuándo debería usar el triple capitán?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Timing advice for TC chip — not a yes/no this GW
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### BB timing with explicit trade-off framing
- **Raw prompt:** "¿me conviene usar el bench boost ahora o guardarlo?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** BB timing with explicit trade-off framing
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Chip sequencing strategy from scratch
- **Raw prompt:** "no he usado ningún chip todavía, ¿cuál uso primero?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Chip sequencing strategy from scratch
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


<!-- Add entries here for chip-related questions blocked by strict chip intent logic -->

---

## Category: Squad / Bench Management
### Start vs bench decision for a named player
- **Raw prompt:** "deberia sentar a Watkins esta semana o lo pongo de titular?"
- **App response:** Blocked — no intent handles a start/bench decision for a named player
- **User need:** User wanted to know whether Watkins is worth starting or should be benched this GW
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** captain_score or player_summary could partially inform this; a 'should I start X' intent or player_summary extension is needed

### Bench vs start swap with nickname ('mbu' for Mbeumo)
- **Raw prompt:** "tengo a mbu en el banquillo y a un defensa mediocre de titular, lo cambio?"
- **App response:** Blocked — nickname 'mbu' not resolved + no intent handles bench/start swap decisions
- **User need:** User (using 'mbu' as a nickname for Mbeumo) wanted to know whether to move Mbeumo from bench to XI
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Two failures: (1) nickname resolution missing for 'mbu', (2) bench-management intent absent

### Club-stacking risk in starting XI
- **Raw prompt:** "tengo 3 jugadores del mismo equipo de titular, es mucho riesgo?"
- **App response:** Blocked — no intent models squad composition or club-concentration risk
- **User need:** User wanted to know if having three starters from the same club is too much exposure
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Meta-squad strategy question; no matching intent

### Budget allocation strategy (cheap GK to free outfield budget)
- **Raw prompt:** "me conviene meter a un portero titular barato para tener mas dinero en otros puestos?"
- **App response:** Blocked — no intent covers positional budget allocation strategy
- **User need:** User wanted to know if using a cheap starting GK to free budget for outfield positions is sound strategy
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Tangentially related to transfer_advice; no intent models positional budget trade-offs

### Bench ordering — expected points optimization
- **Raw prompt:** "¿cómo ordeno mi banquillo para esta jornada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Bench ordering — expected points optimization
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Optimal starting XI from user's squad — needs squad context
- **Raw prompt:** "¿cuál es mi mejor once posible?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Optimal starting XI from user's squad — needs squad context
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Formation recommendation
- **Raw prompt:** "¿qué formación me recomiendas usar esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Formation recommendation
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Bench vs start for expensive asset — rotation risk
- **Raw prompt:** "¿debería dejar a Salah en el banquillo esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Bench vs start for expensive asset — rotation risk
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


<!-- Add entries here for lineup, bench order, formation questions -->

---

## Category: Player Info / Stats
### Price and ownership query not routed to player_summary
- **Raw prompt:** "cual es el precio actual de Palmer y cuanta gente lo tiene?"
- **App response:** Blocked — player_summary SHOULD have caught this; price+ownership is exactly what that intent covers; routing failure
- **User need:** User wanted current price and ownership percentage for Cole Palmer
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** High-severity regression: textbook player_summary query not routed; phrasing 'cual es el precio... y cuanta gente' may not match classifier

### Cumulative season FPL points for a named player
- **Raw prompt:** "cuantos puntos lleva Isak esta temporada en total?"
- **App response:** Blocked — player_summary covers price/ownership/availability but not cumulative season points
- **User need:** User wanted total FPL points Isak has accumulated this season
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Season-total points are available in bootstrap; player_summary should expose this field

### Recent form + transfer-in assessment for named player
- **Raw prompt:** "como le va a Gibbs-White ultimamente, vale la pena ficharlo?"
- **App response:** Blocked — player_summary or transfer_advice SHOULD have caught this; hyphenated name may have contributed to routing failure
- **User need:** User wanted a form-based assessment of Gibbs-White to decide whether to transfer him in
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Hyphenated names (Gibbs-White) may break the name extractor; also needs form data beyond price/ownership

### Identify in-form player by team + position description (no name given)
- **Raw prompt:** "quien es ese delantero del Forest que esta petandolo ahora?"
- **App response:** Blocked — player_resolve matches by name; team+position+form query not supported
- **User need:** User wanted to identify which Nottingham Forest forward is currently outstanding
- **Priority:** P2
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** player_resolve needs team+form filtering capability, not just name matching

### Basic player summary — should be handled
- **Raw prompt:** "dame un resumen de Salah"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Basic player summary — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Form last N games for named player
- **Raw prompt:** "¿cómo ha estado Salah en los últimos 3 partidos?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Form last N games for named player
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### FPL points history for named player
- **Raw prompt:** "¿cuántos puntos ha sacado Palmer en las últimas 4 jornadas?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** FPL points history for named player
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Form table / in-form players ranking
- **Raw prompt:** "¿qué jugador ha subido más puntos últimamente?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Form table / in-form players ranking
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Full season point history
- **Raw prompt:** "dame el historial de puntos de Mbeumo esta temporada"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Full season point history
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Price rise prediction
- **Raw prompt:** "¿va a subir de precio Mbeumo?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Price rise prediction
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Price risers list
- **Raw prompt:** "¿quién está subiendo de precio esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Price risers list
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Price fallers list
- **Raw prompt:** "¿qué jugadores han bajado de precio últimamente?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Price fallers list
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Injury/availability check for named player
- **Raw prompt:** "¿está lesionado Rashford?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Injury/availability check for named player
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Doubts/injury list for the GW
- **Raw prompt:** "¿hay dudas para esta jornada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Doubts/injury list for the GW
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Availability list — yellow flag players
- **Raw prompt:** "¿cuáles son los jugadores en duda para esta semana?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Availability list — yellow flag players
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


### Recent match stats (last N games)
- **Raw prompt:** "dame las stats de los ultimos 5 partidos de cherki"
- **App response:** Partial match — returned basic player summary (name, team, position, price, ownership, availability) but no match-by-match history.
- **User need:** Per-game breakdown for Cherki over his last 5 FPL fixtures: goals, assists, bonus, minutes, FPL points, and ideally upcoming fixture for context.
- **Priority:** P1
- **Source:** Beta tester, 2026-04-30
- **Notes:** The intent was matched to `player_summary` (the identity/price intent) rather than a dedicated `player_history` or `player_form` intent. The FPL API exposes `element-summary/{id}/` with a `history` array of per-GW stats — data is available but the intent slot is missing. "Últimos N partidos" is a distinct and very common ask. Should not collapse into the generic player summary.

---

## Category: Fixture Difficulty / Schedule Analysis
### Fixture run for a team's position group (Newcastle DEF)
- **Raw prompt:** "dame los proximos 5 fixtures de los defensas del Newcastle"
- **App response:** Blocked — player_fixture_run covers a named player; team+position group query not supported
- **User need:** User wanted upcoming fixtures for all Newcastle defenders to assess their FPL value
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** player_fixture_run needs a team-level variant; team+position fixture analysis is a core FPL use case

### GK targets ranked by upcoming fixture difficulty
- **Raw prompt:** "que porteros tienen el mejor calendario las proximas 4 jornadas?"
- **App response:** Blocked — no intent covers position-wide fixture ranking
- **User need:** User wanted a ranked list of goalkeepers with the easiest upcoming fixture runs
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Position-filtered fixture ranking gap; high value — used by FPL managers to find cheap GK options

### Double gameweek check for a named team
- **Raw prompt:** "el Manchester City tiene doble jornada pronto?"
- **App response:** Blocked — current_gameweek covers GW number but not double-GW scheduling by team
- **User need:** User wanted to know if Manchester City has a double gameweek coming up
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Very common FPL planning question; a schedule/double-GW intent is entirely missing

### Teams with worst upcoming fixtures (avoid list)
- **Raw prompt:** "que equipos tienen los peores fixtures las proximas 3 semanas?"
- **App response:** Blocked — no intent covers team-level fixture difficulty ranking
- **User need:** User wanted to identify teams facing the hardest schedule over the next 3 GWs, to know which players to avoid
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Foundational FPL analysis — team FDR ranking — not served by any current intent

### Player fixture run — should be handled
- **Raw prompt:** "dame los próximos fixtures de Haaland"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Player fixture run — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Variation of season-run-in calendar question
- **Raw prompt:** "¿qué equipo tiene los mejores fixtures que le quedan?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Variation of season-run-in calendar question
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Position-filtered fixture run — DEF assets with easy fixture
- **Raw prompt:** "¿qué defensas tienen buen calendario las próximas 5 jornadas?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Position-filtered fixture run — DEF assets with easy fixtures
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Double gameweek detection
- **Raw prompt:** "¿hay algún equipo con doble jornada próximamente?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Double gameweek detection
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Blank GW detection
- **Raw prompt:** "¿qué equipos tienen blank gameweek esta jornada?"
- **App response:** supported but response too thin (< {THIN_RESPONSE_CHARS} chars)
- **App final_text:** "The current Premier League Fantasy gameweek is GW34."
- **User need:** Blank GW detection
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`current_gameweek` outcome=`ok`


### Best remaining fixture calendar (team-level)
- **Raw prompt:** "que equipo tiene el mejor calendario de ahora a la ultima fecha"
- **App response:** Fallback — "I can help with captain picks, player summaries, gameweek information, and player identity, but I cannot currently provide information about team fixture calendars."
- **User need:** Rank all 20 PL teams by fixture difficulty from current GW through GW38, to identify which teams (and therefore their players) are worth targeting for transfers or differential picks.
- **Priority:** P1
- **Source:** Beta tester, 2026-04-30
- **Notes:** Classic end-of-season question. FDR data is already available from the FPL bootstrap API (`fixtures` + `teams`). High overlap with transfer planning — users asking this are almost always trying to decide who to bring in. Aggregate FDR over remaining GWs per team is the expected output format.

---

## Category: Meta / App Behavior
### Private league standings — requires user auth/team ID
- **Raw prompt:** "¿cómo voy en mi liga privada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Private league standings — requires user auth/team ID
- **Priority:** P3
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### User's own season total — requires team context
- **Raw prompt:** "¿cuántos puntos llevo esta temporada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** User's own season total — requires team context
- **Priority:** P3
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


<!-- Add entries here for cases where the user is confused by the app's response itself -->

---


---

## Category: Gameweek Info
### Precise deadline time (not just GW number)
- **Raw prompt:** "cuando cierra el mercado esta semana exactamente?"
- **App response:** Blocked — current_gameweek SHOULD include deadline time; intent likely returns GW number only
- **User need:** User wanted the exact transfer deadline time for the current gameweek
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** current_gameweek must expose deadline_time field, not just GW number

### Active GW vs international break check
- **Raw prompt:** "hay jornada esta semana o hay paron?"
- **App response:** Blocked — current_gameweek SHOULD handle this; 'paron' (break) phrasing not matched by router
- **User need:** User wanted to confirm whether FPL is active this week or paused for an international break
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** current_gameweek should handle 'is there a GW this week' phrasing variants


### Current GW — should be handled
- **Raw prompt:** "¿en qué jornada estamos?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Current GW — should be handled
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Deadline time — not covered by current_gameweek intent
- **Raw prompt:** "¿cuándo es el deadline de la próxima jornada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Deadline time — not covered by current_gameweek intent
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Remaining GW count
- **Raw prompt:** "¿cuántas jornadas quedan?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Remaining GW count
- **Priority:** P2
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


## Category: Other / Uncategorized

<!-- Dump new screenshots here first if category is unclear -->

---

## Category: Player Pick / Start Recommendation
### Specific defender transfer based on fixture reasoning
- **Raw prompt:** "me conviene fichar a Pedro Porro para tener defensa del Spurs con buen fixture?"
- **App response:** Blocked — transfer_advice + player_fixture_run should catch this; fixture-reasoning framing prevented routing
- **User need:** User wanted a recommendation on signing Pedro Porro given Spurs' upcoming favourable fixtures
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Names a specific player + gives fixture rationale — transfer_advice (buy) + player_fixture_run is the natural handler

### NAME_BUG — Spanish 'compara a X' absorbed into player name
- **Raw prompt:** "compara a isak y watkins para esta jornada, cual inicio?"
- **App response:** Wrong intent matched (compare_players, correct) but name extraction failed — lookup key was 'a isak' not 'isak'
- **User need:** User wanted a comparison of Isak vs Watkins to decide which to start this week
- **Priority:** P1
- **Source:** fpl_probe_agents internal scan, 2026-05-02
- **Notes:** Accusative 'a' in 'compara a [player]' absorbed into player token; fix: strip leading 'a ' before player resolution

### Differentials — should be handled
- **Raw prompt:** "dame picks diferenciales para esta jornada"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Differentials — should be handled
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Start recommendation for named player
- **Raw prompt:** "es un buen pick para esta semana gibbs-white"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Start recommendation for named player
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Start/bench decision for named player
- **Raw prompt:** "¿debería poner a Isak de titular esta jornada?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Start/bench decision for named player
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Transfer-in worthiness for named player (not a direct swap)
- **Raw prompt:** "¿vale la pena fichar a Mbeumo ahora?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Transfer-in worthiness for named player (not a direct swap)
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Budget GKP recommendation by position + price filter
- **Raw prompt:** "¿me recomiendas algún portero barato?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Budget GKP recommendation by position + price filter
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`

### Position + budget filtered player recommendation
- **Raw prompt:** "¿qué delantero debería fichar si tengo 6 millones?"
- **App response:** blocked / unsupported intent
- **App final_text:** "I couldn't match that question to a supported query. Supported questions include: captain score for a player, captain rankings, player comparison, transfer advice, chip advice, player fixture run, differential picks, player summary, player lookup, and current gameweek."
- **User need:** Position + budget filtered player recommendation
- **Priority:** P1
- **Source:** catalog_runner automated scan, 2026-04-30
- **Notes:** intent=`unsupported` outcome=`unsupported_intent`


### "Is this player a good pick this week?" (follow-up after player summary)
- **Raw prompt:** "es un buen pick para esta semana?" (after receiving player summary for Gibbs-White)
- **App response:** Fallback — "I can help with questions about captain picks, player summaries, gameweek information, and player identity. Unfortunately, I can't currently advise on general player picks for the gameweek."
- **User need:** Given a specific player already in context (Gibbs-White, MID, £7.6m, Nott'm Forest), assess whether he is worth starting or transferring in for the current GW — considering fixture, form, and ownership.
- **Priority:** P1
- **Source:** Beta tester, 2026-04-30
- **Notes:** This is a natural 2-turn flow: "tell me about X" → "should I play/buy X?". The user already has the player in context from the previous turn. The intent is distinct from captain advice (not asking about armband) and from transfer advice (not asking about budget/hit). It is a start/pick recommendation for a named player. Very common FPL question pattern — blocking it after a player summary feels like a dead end to the user.
