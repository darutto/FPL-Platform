---
title: Dogfooding del armado de equipo 25-26 vía app.benditofantasy.com
found_via: usuario armando su equipo real, contrastando respuestas contra ChatGPT
captured: 2026-08-09
relevant_to: [scoring, contracts, ui, data-quality]
status: new
---

## What prompted this
El usuario está usando el proceso tradicional de armado de equipo como excusa
para mapear qué puede y no puede contestar la app hoy, comparando respuestas
contra ChatGPT en paralelo.

## Findings

### 1. `minutes` puede quedar desactualizado por el cacheo del bootstrap — severity: low
**What happens:** El número de minutos de un jugador puede no reflejar el
partido más reciente si no hubo un restart del servidor desde entonces.
**Evidence:** `element.get("minutes")` viene directo del `bootstrap-static`
oficial de FPL, sin transformación
([find_players.py:153-171](../packages/fpl-grounded-assistant/fpl_grounded_assistant/find_players.py#L153-L171)),
pero el bootstrap se descarga **una sola vez al arrancar el proceso** y queda
cacheado en memoria ([fpl_server.py:118,122-129](../fpl_server.py#L118)). El
redeploy que lo refresca corre en cron semanal (lunes 06:00 UTC,
`.github/workflows/owned-store-refresh.yml`).
**Where:** `fpl_server.py:118-129`
**Why it happens:** No hay invalidación de cache por request ni por evento
(gol, fin de partido); solo por restart del proceso.
**Fix direction:** TTL corto sobre el bootstrap en memoria, o invalidación
disparada por webhook/cron más frecuente que semanal.

### 2. Dos fórmulas de "calificación Bendito" distintas, sin query standalone para ninguna — severity: med
**What happens:** El score que se ve en `/comparar` (`position_score`, ej.
33.7/100 para Konsa) y el que usa `/capitan` (`captain_score`) son **fórmulas
distintas** que pueden ordenar jugadores de forma opuesta, y no existe forma
de pedir el `position_score` de un solo jugador sin pasar por una comparación.
**Evidence:**
`position_score` calculado en
[comparison.py:365-374](../packages/fpl-grounded-assistant/fpl_grounded_assistant/comparison.py#L365-L374),
peso de `form` 30-40% ([position_score.py:110-133](../packages/fpl-grounded-assistant/fpl_grounded_assistant/position_score.py#L110-L133)).
`captain_score` es la fórmula Layer 1 de `fpl-captain-engine`, invocada en
`comparison.py:349-356` — código comentado confirma que pueden rankear
distinto. `V2_ROADMAP.md:217-238` (Track E, "Bendito Fantasy Score
Leaderboard") documenta explícitamente que exponer `position_score` para un
jugador solo/rankeado está **planeado pero no construido**.
**Where:** `comparison.py:349-374`, `position_score.py:110-133`
**Why it happens:** Dos motores de scoring construidos en momentos distintos
(captain vs comparación), nunca unificados ni expuestos por separado.
**Fix direction:** Construir Track E (leaderboard/rating standalone) y, a la
vez, decidir si `captain_score`/`position_score` deben converger o quedar
explícitamente etiquetados como "para qué sirve cada uno" en el copy de la UI.

### 3. Chip wizard: texto libre no completaba la comparación (más grave de lo que parecía) — severity: med — status: **fixed**
**What happens:** El wizard de `/comparar` solo mostraba 3 chips sin pista de
que el chat de abajo seguía funcionando (hallazgo original, severity low). Al
probarlo en vivo en prod, se descubrió que el problema era peor: escribir un
nombre **tampoco completaba la comparación** — `sendMessage` siempre limpiaba
el wizard y mandaba el texto tal cual, así que escribir "ruben dias" durante
`/comparar konsa` disparaba "No player matching 'ruben dias'" en vez de
comparar Konsa vs Dias. Solo tocar un chip armaba el comando canónico.
**Evidence:** `ChatShell.tsx` — el comentario original decía explícitamente
"Any send (manual or wizard-driven) exits an active comparison wizard",
protegido por un test (`compare-wizard.test.tsx`, "manual send exits the
wizard"). Reproducido en prod: capturas de pantalla del usuario mostrando
`/comparar konsa` → `dias` → resultado de búsqueda suelta, no comparación.
**Where:** `packages/fpl-ui/components/chat/ChatShell.tsx` (`sendMessage`),
`packages/fpl-ui/components/chat/SuggestionChips.tsx`
**Fix direction:** hecho — PR [#104](https://github.com/darutto/FPL-Platform/pull/104).
Un envío manual mientras el wizard está armado ahora se compone igual que un
chip tap (`/comparar {typed}` en paso 1, `/comparar {playerA} vs {typed}` en
paso 2); un `/` o `@` explícito sigue funcionando como escape. 8/8 tests del
wizard + 452/452 de la suite completa de `fpl-ui`.

### 4. Snapshot de un solo jugador: dos renderers asimétricos, ninguno es tarjeta compartible — severity: med
**What happens:** Preguntar por un jugador puede caer en dos tools/renderers
distintos con **conjuntos de campos diferentes** — "Konsa" mostró
Precio/Propiedad/Status/Total pts/Form/Mins, mientras "cuántos minutos jugó
Saka" mostró Precio/Propiedad/Estado/Pts totales/PPG/Forma/xG/xA/xGI/ICT/
Minutos. Además, **ninguna de las dos** se renderiza como tarjeta estilo
Bendito Fantasy — ambas caen como burbuja de texto plano y por lo tanto no
tienen botón de compartir.
**Evidence:**
- Dos code paths compiten para la misma pregunta: intent `player_summary` vía
  router → tool `get_player_summary` →
  [renderer.py:78-108](../packages/fpl-grounded-assistant/fpl_grounded_assistant/renderer.py#L78-L108)
  (solo Total pts/Form/Mins, sin PPG/xG/xA/xGI/ICT — esos campos no existen
  en esta función); vs. tool `get_player_snapshot` (LLM tool-calling) →
  [renderer.py:804-837](../packages/fpl-grounded-assistant/fpl_grounded_assistant/renderer.py#L804-L837)
  (construye siempre Pts totales/PPG/Forma/xG/xA/xGI/ICT/Minutos, sin
  condicionar por posición/nulls). La asimetría es **qué tool respondió**, no
  disponibilidad de datos.
- Frontend: `player_summary`/`player_resolve` están explícitamente listados
  como `TEXT-ONLY (structured rendering deferred)` en
  [intent-renderer.ts:29-30](../packages/fpl-ui/lib/intent-renderer.ts#L29-L30)
  y repetido en `IntentRenderer.tsx:24-25`. No existe ningún componente
  `PlayerCard`/`PlayerSnapshotCard` en `packages/fpl-ui`.
- `build_generic_card` (`generic_card.py:520-538`) no incluye
  `player_summary` ni `get_player_snapshot` en su mapeo de intents → tarjeta,
  así que `response.generic_card` queda `None` y `selectIntentView()` cae en
  `return null` ([intent-renderer.ts:156](../packages/fpl-ui/lib/intent-renderer.ts#L156)).
- El botón de compartir (`ShareActions`) solo se monta cuando `hasFplCard` es
  true, es decir `selectIntentView(response) != null`
  ([MessageList.tsx:129-133,150-152](../packages/fpl-ui/components/chat/MessageList.tsx#L129-L152))
  — confirmado que ambas respuestas quedan fuera del mecanismo de compartir
  por construcción, no por accidente puntual.
**Where:** `router.py:2014`, `get_player_snapshot.py:264-329`,
`renderer.py:78-108` y `:804-837`, `generic_card.py:520-538`,
`intent-renderer.ts:29-30,156`, `MessageList.tsx:129-152`
**Why it happens:** Dos tools de "info de un jugador" construidas en
momentos distintos (legacy `get_player_summary` vs P2 `get_player_snapshot`)
nunca convergieron en un solo contrato de salida ni se conectaron al sistema
de generic_card/share que sí tienen otros intents (injuries, form, price
changes, fixtures).
**Fix direction:** unificar en un solo tool/renderer para "info de un
jugador" (deprecar uno de los dos, o hacer que ambos produzcan el mismo
contrato), y agregar `player_summary`/`get_player_snapshot` al mapeo de
`build_generic_card` para que salga como tarjeta compartible como el resto de
los intents estructurados.

## Open questions
- ¿Cuál de los dos tools (`get_player_summary` vs `get_player_snapshot`) es
  el que se quiere mantener como fuente de verdad de cara a construir la
  tarjeta? Definir esto probablemente destrabe el finding 4 y simplifique el
  finding 2 (dónde vive el score) al mismo tiempo.
- ¿Vale la pena que el TTL del bootstrap (finding 1) se resuelva junto con el
  trabajo de owned-store-refresh, o es un fix aislado y chico?
