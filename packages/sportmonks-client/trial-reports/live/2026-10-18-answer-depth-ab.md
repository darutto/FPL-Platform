# A/B de profundidad de respuesta: FPL solo vs FPL + Sportmonks (GW7, 18 oct 2026)

Experimento aprobado por Leo el 2026-10-17. Mismo chat, mismo modelo, mismas 15 preguntas. Brazo A = FPL solo. Brazo B = FPL + las herramientas de Football Intelligence (FI) leyendo el almacén local del trial.

## Resultado en una línea

**El brazo B no se pudo ejecutar.** El runtime de las herramientas FI rechaza por diseño un almacén `live_trial_local`, y las variables de desarrollo no lo abren. No se tocó ningún guard. El brazo A se ejecutó y quedó congelado mucho antes de la hora límite.

## Congelado

| | |
|---|---|
| Congelado a las | 2026-10-17T21:07:15Z (límite: 2026-10-18T12:30:00Z) |
| sha256 de `frozen.json` | `101203f1c054354a72957eca46c367b0b45a1c74e80d8a763f4ce5490c3b0806` |
| sha256 de `answers_A.jsonl` (crudo) | `a3c28c5d95809c7859fb5fe084213c605fabcab36d520083f2b8b0b097f96b9e` |
| Ubicación (local, git-ignored) | `wt-fi9-live/packages/sportmonks-client/trial-output/answer-depth-ab/` |

## Por qué el brazo B está bloqueado (exacto)

1. Las variables de desarrollo (`ENV_ALLOW` / `ENV_CAPTURE` de `competition_calendar.py`) abren **solo** `GET /fixtures/competitions`, es decir, el calendario multicompetición. Ese endpoint no es una herramienta del chat: el orquestador nunca lo llama.
2. Las herramientas FI del chat (`get_player_intelligence`, `get_expected_minutes`, `get_tactical_role`, `get_fixture_context`) pasan por `football_intelligence_runtime._load_runtime()`. Esa función:
   - abre el almacén con `RuntimeBuildHandle(root)` con `allow_live_trial_local=False` fijo. El código dice: "Only the trial's own analysis scripts set this. The serving runtime never does.";
   - después llama a `refuse_live_trial()` sobre los manifiestos de contexto y de features **sin ninguna excepción por variable de entorno** (#424);
   - el almacén del trial (`runs/gw6-final/store`, built_at 2026-10-13) lleva `assumption_status = live_trial_local` y `normalizer = live-trial-v1`.
3. Además, la estructura de carpetas no coincide. El runtime espera `_football_latest.json`, `_football_v2_latest.json`, `features/` e `identity/` en la raíz. El almacén del trial tiene `context/`, `features/`, `source/` y `v1/<competición>/`, y no tiene `identity/`. Con `FPL_FOOTBALL_ROOT` apuntando a `store` o a `store2`, el runtime devuelve `None` y la herramienta responde `missing_context / feature_build_unavailable`. Una copia reordenada en scratch (borrada después) se paró en la validación de punteros (`RemoteValidationError`), antes de llegar al rechazo de procedencia.
4. Aunque se abriera, el almacén solo llega hasta GW6 (construido el 13 oct). No tiene datos de GW7.

Para desbloquearlo hace falta una decisión, no un truco: una vía de desarrollo explícita en el runtime del asistente (por ejemplo, el mismo `allow_live_trial_local` que usan los scripts del trial, detrás de las dos variables de desarrollo, con su test de "nunca en prod"), más un almacén construido con la estructura que espera el runtime. Es un cambio de guard, y le toca decidirlo a c4 y Leo.

## Configuración del brazo A (leída de la traza, no de la configuración)

- Modelo real en el audit trace: **openai / gpt-5.6-luna en 15 de 15 preguntas**. El orquestador y el resolver se fijaron a openai/luna; el `.env` local apunta a Gemini.
- `FOOTBALL_INTELLIGENCE_ENABLED` apagado. Bootstrap FPL en vivo (GW7 en curso, deadline de GW8 el 23 oct). team_id 68643 solo en la Q15.
- Cambio de jugador: **Salah no aparece en el bootstrap del 17 oct**. La Q12 usa a Szoboszlai, el MID más elegido del Liverpool (21,4 %).
- Limitación local: aquí no hay almacén zonal (Understat) de 2026-27, así que la Q8 salió `unsupported`. En prod podría salir distinta.
- El chat hizo **13 `web_fetch`** (Q1, Q6, Q7 y Q9). Parte de lo que el brazo A sabe "fuera de FPL" sale de la web, no de Sportmonks.

## Medidas por pregunta (brazo A; brazo B = no ejecutado)

Hechos = afirmaciones concretas y comprobables. "Fuera de FPL" = hechos que FPL no puede dar. Erróneos = comprobados contra el bootstrap y el `/fixtures` del 17 oct.

| Q | Herramientas (A) | Hechos | Fuera de FPL | Erróneos o inventados | Nota |
|---|---|---|---|---|---|
| 1 Bruno titular | web_fetch, get_gameweek_context | 0 | 0 | 0 | "No se puede confirmar" |
| 2 Saka juega | get_player_snapshot ×2 | 2 | 0 | 0 | Disponible; sin XI previsto |
| 3 Defensa ARS | get_transfer_suggestion, get_team_schedule | 14 | 0 | 0 | Calafiori |
| 4 BHA portería a cero | get_fixture_outlook | 4 | 0 | 0 | "Buena posibilidad" (FDR 2) |
| 5 Goleador BOU–SUN | team_snapshot ×2, compare_players, team_schedule ×2 | 10 | 0 | 0 | Brobbey |
| 6 Laterales ARS | web_fetch ×2 | 2 | 2 (web) | 0 por ahora | Timber LD y Calafiori LI, previsión de la web; se comprueba el domingo |
| 7 Posición real LEE/MUN | web_fetch ×6 | 1 | 0 | 0 | "No puedo confirmarlo" |
| 8 Atacante ARS vs NFO | get_zonal_opportunity ×2 | 0 | 0 | 0 | `unsupported`: sin datos zonales |
| 9 Rotación TOT | web_fetch ×4 | 0 | 0 | 0 | "Sin confirmación pública" |
| 10 Diferencial SUN | differential_picks ×2, team_snapshot, injury_list | 17 | 0 | **1** | "Sunderland recibe al Leeds mañana": falso, mañana juega en Bournemouth (SUN–LEE es GW8) |
| 11 Palmer GW8 | get_transfer_suggestion, get_player_snapshot | 14 | 0 | 0 | Sí, con reservas |
| 12 Haaland vs Szoboszlai | captain_score ×2, rank_captain_candidates | 11 | 0 | 0 (1 omisión) | Haaland. Omite que Szoboszlai está lesionado (isquio, 0 %) |
| 13 Portero barato | get_transfer_suggestion ×2 | 10 | 0 | 0 | Rushworth |
| 14 DEF <5M más adelantados | rank_players_by_metric | 37 | 0 | 0 | Usa xGI como proxy; no tiene la posición real |
| 15 Vender (68643) | get_my_squad, get_player_snapshot ×4 | 14 | 0 | 0 | Ødegaard |
| **Total** | FI llamadas: 0 de 15 (FI apagado) | **136** | **2** | **1** | |

Otras observaciones:

- **El único error es de origen.** `get_team_snapshot` lista los próximos partidos desde GW8 cuando GW7 está en curso, y el modelo leyó ese primer partido como "mañana".
- **Un dato raro que sale de la herramienta, no del modelo (Q12):** `get_captain_score` le da a Haaland 619 minutos jugados sobre 540 disponibles (7 titularidades en 6 partidos). La respuesta lo repite como "minutos registrados superan los disponibles".
- **Las preguntas donde el brazo A dice "no lo sé" son las que FI promete cubrir:** XI previsto (Q1, Q2, Q6), posición real (Q7, Q14), debilidad del rival (Q8) y rotación o calendario de Europa y copas (Q9). Esto es una hipótesis para el brazo B, no un resultado.

## Extractos (brazo A)

> Q10: "**Partido:** Sunderland recibe al Leeds mañana; dificultad media." (falso: mañana es Bournemouth–Sunderland)

> Q7: "No puedo confirmarlo con seguridad solo con la clasificación de FPL: esta asigna una posición fija, mientras que la posición real puede variar…"

> Q8: "No hay datos zonales de Nottingham Forest disponibles para identificar qué atacante del Arsenal encaja mejor…"

## Después de los partidos (Q1–Q10)

Placeholder: no se ha corregido nada todavía. Después del lunes 19 a las 21:30 UTC:

```
cd packages/fpl-grounded-assistant
python scripts/measure_fi_answer_depth_ab.py outcomes --gw 7 --out-dir <trial-output>/answer-depth-ab
```

El comando escribe `outcomes_gw7.json` (minutos, titularidades, goles y porterías a cero de FPL; sin Sportmonks) y `grading_gw7.json`, con un veredicto vacío por pregunta. El veredicto de acierto o fallo lo pone una persona. Las páginas ciegas (`blind`) necesitan los dos brazos, así que no se generaron.
