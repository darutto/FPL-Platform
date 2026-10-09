# Bloque 10 — Fase 0: viabilidad y ruteo («Háblame de X»)

Spec: el plan aprobado por Leo (`el-bug-en-algun-adaptive-journal.md`). Solo medición; no cambia código de producto.
Fecha 2026-10-08, base `origin/main` 3b500bc. Modelo forzado `openai/gpt-5.6-luna`. Tope declarado 1,50 USD; gasto real 0,0351 USD (36 llamadas) + 6 consultas a `/ask` de prod.

## Evidencia

| Fichero | Contenido |
|---|---|
| `artifacts/b10-phase0-routing-before.jsonl` | 12 frases × R=3 = 36 observaciones (secuencia de herramientas, args, intent/outcome, texto) |
| `artifacts/b10-bootstrap-2026-10-08.json` | bootstrap FPL en vivo del día (jornada 5 actual, 6 siguiente) con `team_fixtures` y `_gw_fixtures`; el del corpus viejo (2026-08-18) tenía la temporada anterior |
| `artifacts/b10-phase0-prod-store-probe-2026-10-08.jsonl` | respuestas completas de `/ask` de prod (con `debug.raw_output`) |
| `packages/fpl-grounded-assistant/scripts/measure_b10_player_general_routing.py` | corpus inline (SHA256 estampado por fila) + runner sobre `measure_tool_routing.run_one` |

Reproducir: desde `packages/fpl-grounded-assistant`, `python scripts/measure_b10_player_general_routing.py --out <jsonl> --reps 3` (necesita `.env` con la clave de OpenAI).

## 1. Ruteo — gate superado, sin tocar schema ni prompt

| Familia | Resultado |
|---|---|
| Generales (5 frases: Palmer, Haaland ×2 formas, Saka, Bruno Fernandes) | **15/15** → `get_player_snapshot`, `status=ok` |
| Ambigua «Háblame de Palmer» (Cole CHE / Alex IPS) | **3/3** `get_player_snapshot` → `status=ambiguous`; el wizard se conserva |
| Control zonal | 3/3 `get_player_zonal_outlook` |
| Control historial | 3/3 `get_player_form` |
| Control calendario | 3/3 `get_team_schedule` |
| Control ranking | 3/3 `rank_players_by_metric` |

Recomendación (aparte, no es gate): «¿Vale la pena fichar a Cole Palmer?» → snapshot 2/3, `get_transfer_suggestion` 1/3. «¿Me conviene vender a Haaland?» → snapshot 1/3, `get_my_squad` 1/3 (`no_team_connected`), sin herramienta 1/3. Estas preguntas no pasan siempre por la ficha y la composición no las cubrirá cuando no lo hagan. Es esperado y no está en el alcance.

Salvedad del entorno: en el worktree `packages/fpl-tactical/data` no existe, así que el control zonal devuelve `missing_context` (3/3). Solo vale como prueba de ruteo, no de contenido.

## 2. Viabilidad en el store desplegado (prod, `/healthz`: store 2026-2027, `merged_at` 2026-10-05, sync ok)

Consultado vía `get_player_zonal_outlook` en prod (el store no es accesible directamente desde aquí):

| Jugador | Resultado | Perfil | Procedencia |
|---|---|---|---|
| Cole Palmer (CHE) | ok, nombre del store exacto «Cole Palmer» | 1 zona: in-box / central, share 0.5923 | 2026-27, `thin`, 50 partidos, 1398 tiros |
| Erling Haaland (MCI) | ok, «Erling Haaland» | 1 zona: in-box / central, share 0.9824 | igual |
| Bukayo Saka (ARS) | ok | 1 zona, share 0.8069; todas neutrales | igual |
| Robert Sánchez (CHE, portero) | sin perfil (`orchestrator_no_grounded_tool`, «no hay un perfil de tiros válido») | — | — |
| Alisson (LIV, portero) | sin perfil, igual | — | — |
| David Raya (ARS, portero) | sin perfil, igual | — | — |

**Palmer y Haaland tienen perfil utilizable.** Ambos con nombre completo exacto en el store (no hace falta subcadena).
Propuesta de gate para el jugador «sin perfil»: **Robert Sánchez** (portero). Para el nombre ambiguo: **«Palmer»** (Cole/Alex), que dio `ambiguous` 3/3.

Límite de esta comprobación: confirma que el motor actual (búsqueda por nombre) da perfil; la comprobación con el adaptador **estricto** (nombre completo normalizado + equipo + candidato único) llega en el PR backend, porque el store de prod no se puede leer desde aquí. Palmer y Haaland cumplirían la regla (nombre del store == nombre completo FPL, equipo coincide).

## 3. Hallazgos que condicionan el backend

- **Procedencia `thin`**: con solo 5 jornadas el aviso es «⚠ Datos de 2026-27, sólo 5 jornadas de liga — muestra corta para una lectura de liga». La sección debe mostrarlo (ya previsto).
- **Una sola zona**: los tres perfiles tienen una única zona sobre umbral (in-box / central); la sección «Zonas» tendrá un chip. `lib/defensive-zones.ts` debe cubrir las zonas de la salida, no solo las del área.
- **Estado del fixture**: en el bootstrap de hoy, la jornada 5 (actual) tiene sus 10 partidos `started/finished/finished_provisional = True`; la 6 todos `False`. El `/ask` de prod ya empieza el calendario en la J6. Con el filtro por estado explícito, «actual…actual+2» hoy da J6–J7 (J5 terminada se excluye) y puede dar menos de 3 jornadas; el texto «próximas 3 jornadas» debe tolerarlo.
- La estructura de `team_fixtures` del bootstrap no trae `fixture_id` ni estado; el estado sale de `_gw_fixtures` (campos `started`, `finished`, `finished_provisional`, `event`, `id`). Se verificará en el PR backend contra el payload real.
