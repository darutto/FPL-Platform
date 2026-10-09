# Bloque 10 — PR backend: «Zonas» dentro de la ficha de jugador

Spec: el plan aprobado por Leo + las decisiones de revisión del 8-oct (ventana, proveedor de estado). Fase 0: PR #394.

## Qué hace

`get_player_snapshot._ok()` añade `player["zonal"]` (composición determinista, sin LLM extra) cuando se puede demostrar la identidad y hay calendario pendiente. `PlayerSnapshotMeta.zonal` (nullable) lo lleva al `/ask`; el renderer de texto y una regla de prompt de una línea cubren las dos salidas. Contrato: `FINAL_RESPONSE_CONTRACT.md` §`player_snapshot.zonal`; espejo TS en `fpl-ui/lib/types.ts`.

## Decisiones (y por qué)

| Tema | Decisión |
|---|---|
| Estado del fixture | `bootstrap["_gw_fixtures"]` (tests) → una petición `/fixtures/` con caché de 60 s (timeout 2.5 s, sin reintentos; vacío/malformado/fallido no se cachea). `team_fixtures` del servidor solo trae `finished` y se ensambla una vez al arrancar, así que **no** se usa. |
| Ventana | Primera jornada con un partido pendiente del equipo actual + las dos siguientes. Pendiente = `started`, `finished`, `finished_provisional` los tres `false` explícitos; en curso/terminado fuera; flag ausente → omitir. Hoy: J6–J8. |
| Identidad | El store solo guarda nombre. Nombre completo normalizado (o resolver exacto compartido) → exactamente un perfil de store y un elemento FPL, y equipo del store == equipo actual. Traspaso sin enlace → omitir. Sin prefijo/subcadena. Sin crosswalk por ID (los ids de `corpus.py` son sintéticos). |
| `share` | Fracción 0–1 en backend y contrato; porcentaje solo al mostrar (el renderer de texto lo convierte; la UI lo hará una vez en el componente). |
| `no_data` | Fila «sin datos zonales del rival»; si todos lo son, veredicto de disponibilidad (`verdict_kind: no_data`). |
| Aislamiento | Cualquier fallo/dato inválido descarta solo la clave `zonal`; `status` y `PlayerSnapshotMeta` intactos. Motivo interno en el log `player_zonal`. |
| Motor | `get_player_zonal_outlook` se parte en un selector por nombre (sin cambios de comportamiento) y `build_player_outlook(...)`, entrada estricta que recibe el perfil ya elegido. Las herramientas zonales existentes no cambian. |
| Prompt | Regla `PLAYER_ZONAL`: una frase con el veredicto, sin volcar la tabla, con la advertencia de procedencia si no es `current`. |

## Verificación

- Tests: `tests/test_player_snapshot_zonal.py` (59, sin red) + suite del paquete 3193 pasan. `conftest.py` bloquea el seam de red para toda la suite.
- Contract gate local (`scripts/run_contract_gate.sh`): 15/16 verde; el 16.º (`run_phase_fi3_tests.py`, suite de sportmonks-client) fallaba solo por `PermissionError` del directorio temporal de pytest en esta máquina; con un `PYTEST_DEBUG_TEMPROOT` propio pasa 5/5.
- Mutaciones (`scripts/mutation_b10_player_zonal.py`, informe `artifacts/b10-mutation-report.txt`): 19 mutantes, uno por guarda (identidad ×5, aislamiento ×4, estado del fixture ×8, `no_data` ×2, unidad de `share` ×1 — dos de aislamiento comparten fila): **19 muertos, 0 vivos**. Un primer pase dejó vivo «provisional finish ignored»; se añadió el test que lo mata.
- Auditoría de identidad (`scripts/audit_b10_zonal_identity.py`, `artifacts/b10-identity-audit-2025-26-store.json`), store local 2025-26 contra el bootstrap vivo de hoy: 421 elementos con minutos → 173 resueltos (144 nombre completo, 29 resolver exacto), 213 sin perfil, 35 rechazados por equipo (traspasos/ascensos). De los 303 perfiles del store: 173 reclamados por exactamente un elemento, 130 por ninguno, **0 por varios**. Control independiente (xG del store vs xG FPL de 2025-26 enlazado por `code`): 151 pares, mediana del cociente 1,059, 151/151 dentro de [0,4–2,5], sin atípicos. **Límite:** el store de prod 2026-27 no se puede leer desde aquí; esta auditoría valida el método, no la cobertura de prod.
- `/ask` servido (`artifacts/b10-served-ask-local.jsonl` = antes de la regla de procedencia del prompt; `b10-served-ask-local-r2.jsonl` = código final; `scripts/measure_b10_served_ask.py`, openai/gpt-5.6-luna, 2 × 24 llamadas; techo declarado 1,00 USD; el script no calcula el coste real, el techo previo por llamada da ≤ 0,19 USD en total):
  - Palmer y Haaland: 1 `player_snapshot` con `zonal` (3/3 cada uno), una sola tarjeta, el texto menciona el cruce (Palmer: J7 Everton favorable; Haaland: sin cruce destacado, coherente con el bloque) y, tras la regla de procedencia, la advertencia de temporada 3/3 + 3/3.
  - Robert Sánchez: ficha normal, sin `zonal` (3/3). «Palmer»: ambiguo, 2 sugerencias de wizard (3/3).
  - Entorno: el store local es el de 2025-26 puesto bajo la clave actual, así que la procedencia sale `stale_season` («⚠ Datos de 2025-26, no de la temporada en curso»). Sirve para fontanería y forma, no para los números de esta temporada.
- Latencia (herramienta, sin LLM; `header.tool_latency` del JSONL): arranque en frío 1,55 s / 1,71 s (lectura del parquet + petición de fixtures); store caliente y fixtures fríos 0,74 s; caliente 64 ms frente a 58 ms sin la composición (+6 ms). Umbral fijado antes del merge: caliente ≤ +50 ms y frío ≤ 3 s — cumplido. El store se lee una vez por versión (clave ruta+mtime+tamaño); la identidad y el outlook comparten esa lectura.
  - En el turno completo, la mediana pasa de 6,3→7,5 s (Palmer) y 4,5→7,0 s (Haaland): varía con la longitud de la respuesta del modelo; la herramienta aporta ~6 ms en caliente.

## Salvedades

- Prod 2026-27 está `thin` (5 jornadas): la sección lleva la advertencia y el texto del modelo también.
- Solo se comprueba el contrato de transporte; la sección «Zonas» de `PlayerCard` llega en el PR de UI.
- El `_bootstrap` congelado al arrancar afecta a toda la app; es una carta aparte (no se toca aquí).
