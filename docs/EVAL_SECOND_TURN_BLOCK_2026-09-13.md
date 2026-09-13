# Evaluación en prod — bloque "segundo turno" (i79, i81, i82, i60)

Fecha: 2026-09-13. Estado del código: i79/i81/i82 en `main` y desplegados; i60 en PR #262 (pendiente de merge → las preguntas de la sección 4 solo aplican después).

Regla de lectura: cada pregunta dice **dónde se lee el resultado**. Nunca dar por buena una carta leyendo solo el texto de la respuesta; se lee del audit log, del `debug` del payload o del DOM.

Ya comprobado hoy por script (`scripts/verify_prod_rollover.py --expected-season 2026-2027`, user id fresco):

| Comprobación | Resultado |
|---|---|
| "¿Quién hizo más puntos en la jornada 3?" | `tool_calls=['get_historical_gameweek_top_scorer']`, `tool_input={'gw': 3}`, `raw_output.season='2026-2027'`, 1 fila: Mitchell (CRY, DEF) 15 pts. **OK** |
| "¿Cuántos puntos hizo Salah la temporada pasada?" | `tool_calls=['get_player_season_points']` (ruteo correcto) pero `final_text="No historical data for season '2025-2026'. Available seasons: 2026-2027."` — **el contenedor solo sincroniza la temporada en curso** (`fpl_server.py:783`). Límite de datos, no de i82. Ver §5. |
| Nota operativa | el `--user-id` por defecto del script (`verify-prod-rollover-i73`) ya agotó su cuota free de 5/día; usar `--user-id` distinto cada corrida. |

---

## 1. i79 — identidad en el segundo turno

**Preparación:** sesión **premium real en el navegador** (nunca `curl` con cabeceras: eso prueba justo el camino vulnerable). Cada pregunta lleva un marcador único para correlacionar en el audit log: sustituye `<T>` por la hora `HHMM`.

| # | Pregunta (escribir tal cual) | Camino | Esperado en pantalla |
|---|---|---|---|
| 1.1 | `[i79-<T>-1] ¿Quién es el mejor capitán esta jornada?` | `/ask` | respuesta normal, indicador de cuota premium |
| 1.2 | `[i79-<T>-2] ¿Y para la siguiente jornada?` | `/ask` | respuesta normal |
| 1.3 | `[i79-<T>-3] ¿Cómo va mi plantilla?` | `/ask` | usa tu plantilla (team_id) — si sale "no tengo tu equipo", ya falló antes del turno 4 |
| — | pulsar **"Seguir conversación →"** | crea sesión | — |
| 1.4 | `[i79-<T>-4] ¿Y de mi plantilla quién es el mejor capitán?` | `/session/{id}/ask` | **sigue usando tu plantilla y tu tier** |
| 1.5 | `[i79-<T>-5] ¿Cuántos mensajes me quedan hoy?` | `/session/{id}/ask` | cubo premium, no free |

**Dónde se lee:** `railway ssh` → audit log, filtrar por `i79-<T>`. Los **cinco** registros deben tener el mismo `user_id` hasheado y el mismo `tier` (`patreon_premium`). Si 1.4/1.5 salen `anonymous`/`free`, i79 no está entregada.

**Forja anónima (esta sí por `curl`, sin cookie de sesión):**

```
curl -s -X POST https://<vercel-app>/api/proxy \
  -H "Content-Type: application/json" \
  -H "x-user-id: user_forjado" -H "x-user-tier: patreon_premium" \
  -d '{"question":"[i79-<T>-forja] ¿Quién es el mejor capitán?"}'
```

**Dónde se lee:** audit log, entrada `i79-<T>-forja` → `user_id` = hash de `anonymous`, `tier=free`. Si aparece `patreon_premium`, la frontera no está.

---

## 2. i81 — encabezados y listas numeradas

| # | Pregunta | Esperado en pantalla (captura) |
|---|---|---|
| 2.1 | `Dame un análisis completo del Newcastle contra Leeds: defensa, ataque y a quién capitanear` | encabezados con jerarquía visual, **ningún `###` literal** |
| 2.2 | `Dame 3 opciones de capitán ordenadas y explica cada una` | lista `1. 2. 3.` numerada por el navegador, no "1." como texto plano |
| 2.3 | `Compárame Haaland y Salah punto por punto: forma, fixtures, precio` | viñetas y numeración **no mezcladas** en una sola lista |

**Dónde se lee:** DOM (inspector): `<h2>/<h3>` y `<ol><li>`; y que `textContent` no contenga `#`. Adjuntar captura.

---

## 3. i82 — herramientas del owned store

| # | Pregunta | Esperado | Dónde se lee |
|---|---|---|---|
| 3.1 | `¿Quién hizo más puntos en la jornada 3?` | Mitchell (CRY) 15 pts, temporada 2026-27 | `debug.routing_trace.orchestrator_tool_calls` ∋ `get_historical_gameweek_top_scorer`; `debug.raw_output.season == "2026-2027"`, `entries` ≥ 1 |
| 3.2 | `¿Quién fue el jugador de la jornada 1?` | fila de J1 | ídem, `tool_input.gw == 1` |
| 3.3 | `Dame la tabla de jugador de la jornada de esta temporada` | J1–J3 (las cerradas), nada de la abierta | `raw_output.entries` con 3 filas |
| 3.4 | `¿Quién hizo más puntos en la jornada 4?` (si J4 sigue abierta) | texto "La jornada 4 de 2026-2027 aún no ha terminado." | `raw_output.code == "gameweek_not_finished"` — **no** `gw_not_found` |
| 3.5 | `¿Quién hizo más puntos en la jornada 40?` | error de argumento | `raw_output.code == "invalid_gw"` |
| 3.6 | `¿Cuándo cierra el deadline de la jornada 4?` | deadline | `tool_calls` ∋ `get_gameweek_context`, **no** top_scorer (control) |
| 3.7 | `¿Quién es el máximo goleador de la liga?` | ranking por goles | `tool_calls` ∋ `rank_players_by_metric`, **no** top_scorer (control) |
| 3.8 | `¿Quién fue el máximo goleador de la temporada pasada?` | texto fijo: "No tengo goles por jornada de temporadas pasadas; sí puedo decirte quién hizo más **puntos**. ¿Te sirve?" | `debug.routing_trace.branch == "unsupported"`, `orchestrator_called == false` (regla determinista, ninguna llamada al modelo) |
| 3.9 | `¿Cuántos puntos lleva Salah esta temporada?` | total de la temporada en curso | `tool_calls` ∋ `get_player_snapshot`, **no** season_points (control) |
| 3.10 | `¿Cuántos puntos hizo Salah la temporada pasada?` | **hoy falla por datos** (§5): "No historical data for season '2025-2026'" | `tool_calls` ∋ `get_player_season_points` (el ruteo es correcto); pasará a OK cuando el store de prod tenga 2025-2026 |

Para leer `debug` desde el navegador: enviar con `debug: true` por `/api/proxy` (DevTools → Network → payload) o repetir la pregunta con `scripts/verify_prod_rollover.py`.

Límite conocido (anotar en la carta): `_PAST_SEASON_RE` dispara con cualquier `YYYY-YY` explícito, también el de la temporada actual — `¿Quién es el máximo goleador de la 2026-27?` recibirá el texto fijo de 3.8 en vez de ir a `rank_players_by_metric`.

---

## 4. i60 — chips de ambigüedad (tras merge de #262)

**Preparación:** medir qué nombre es ambiguo **hoy** en el bootstrap, no asumirlo:

```
python - <<'EOF'
import requests, collections
els = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/").json()["elements"]
c = collections.Counter(e["web_name"].lower() for e in els if e["element_type"] in (1,2,3,4))
print([n for n, k in c.items() if k > 1][:15])
EOF
```

Sustituye `<AMBIGUO>` por uno de esa lista (p. ej. `Gabriel`, `Silva`, `Rodrigo` según salga).

| # | Pregunta | Esperado en pantalla | Dónde se lee |
|---|---|---|---|
| 4.1 | `¿Cómo viene <AMBIGUO> en las últimas 5 jornadas?` | picker con chips `Nombre (CLUB)`, uno por candidato; no texto en inglés | payload: `intent == "player_form"`, `outcome == "ambiguous"`, `suggestions[*].player_id` presente |
| 4.2 | clic en un chip de 4.1 | forma **del jugador elegido** | Network: la petición lleva `selected_player_id` = id del chip; la respuesta final devuelve ese `player_id` |
| 4.3 | `Puntos de <AMBIGUO> la temporada pasada` | chips `Nombre (CLUB)` **sin** id, con la temporada en el texto | `suggestions[*].kind == "historical_player_rewrite"`, sin `player_id`, `send_text` termina en `en la temporada 2025-2026` — **hoy la ambigüedad no se producirá en prod** porque el store no tiene 2025-2026 (§5); probar 4.3/4.4 tras restaurarla, o localmente con `FPL_HISTORICAL_ROOT` |
| 4.4 | clic en un chip de 4.3 | puntos del jugador y temporada correctos | Network: `question == send_text`, **sin** `selected_player_id`; respuesta final con `player.id` = id histórico del candidato elegido y `season == 2025-2026` |
| 4.5 | `Puntos de Mohamed Salah (ZZZ) en la temporada 2025-2026` (club que no existe) | sigue ambiguo, no elige en silencio | `outcome == "ambiguous"`, mismos candidatos que sin club |
| 4.6 | `¿Quién es <AMBIGUO>?` | picker como siempre (regresión del wizard de snapshot) | `intent == "player_snapshot"` |

---

## 5. Hallazgo abierto (fuera del bloque, bloquea 3.10 / 4.3 / 4.4)

`fpl_server.py:783` llama `sync_owned_store_from_r2()` sin `season`, así que el contenedor de Railway solo trae `CURRENT_SEASON` (2026-2027). Toda pregunta de temporada pasada devuelve `season_not_found` en prod aunque localmente (store con 2016-2026) funcione. Propuesta de carta: "sincronizar también la temporada anterior al arrancar (si existe en R2; comprobar con `inspect-r2-stores` pasando `2025-2026`)". No es i82 ni i60: el ruteo y los argumentos ya están bien.
