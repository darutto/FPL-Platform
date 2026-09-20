# i109 — `measure_tool_routing.py --team-id`: el instrumento conecta el equipo; el modelo decide si lo mira

**Fecha:** 2026-09-20 · **Base:** `origin/main` = `5df06a7` · **Modelo:** `openai/gpt-5.6-luna` (pin del
script = prod) · **Corpus:** `scripts/tool_routing_corpus.py` blob `7c66740c1af4027c5a48cb41840834742ce58ace`
(sin tocar) · **Bootstrap:** `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json` (events: sin
`is_current`, `is_next=1` → `get_my_squad` resuelve GW1) · **Equipo:** 68643 (chequeo previo gratis:
`get_my_squad` → `status=ok`, 15 picks) · **R=3** · **Tope de gasto declarado:** $1.00 · **Gastado:**
$0.1277 (A $0.0367 + B $0.0348 + C $0.0562, 126 llamadas, 0 excepciones, 0 sin precio).

**Datos crudos (JSONL, una fila por llamada, escritos antes de cualquier agregado):**
- A — script de `origin/main` sin flag (referencia): `field-notes/artifacts/i109-team-id-gate-2026-09-20-A-ref-main-no-flag.jsonl`
- B — script nuevo sin flag: `…-B-new-no-flag.jsonl`
- C — script nuevo `--team-id 68643`: `…-C-new-team-68643.jsonl`

Los tres brazos corrieron en paralelo (misma franja horaria) sobre los 14 ids del plan:
`cvg-01/02/03/04/05/09/10/11/12, ad-03/04/05/07/10`.

## Qué cambia en el instrumento

- `--team-id N` (o env `FPL_MEASURE_TEAM_ID`, el flag gana; env no numérico aborta). `run_one` recibe
  `team_id=` por keyword; `bootstrap_for_call` devuelve una **copia superficial** con `_my_team_id`
  (misma clave y misma regla que `harness.ask_v2` / `get_my_squad.py`) y sin flag devuelve el mismo
  objeto, intacto. El dict compartido nunca se muta (test lo fija).
- Columnas nuevas en cada fila: `team_id_present: bool` y `my_squad_result` ∈ `squad | no_team |
  not_called | error`, leído del `tool_calls_trace` (`get_my_squad` con `status=ok` y `players` no
  vacío = `squad`), nunca del texto ni de la pregunta. **`error` es un cuarto valor que el plan no
  listaba:** lo agregué para que un id malo o un fallo de red no se lean como "el flag no llegó a la
  herramienta" (`no_team`). En este gate no apareció (0/126).
- Los demás scripts que llaman `base.run_one(q, rep, bootstrap, api_key)` posicionalmente siguen
  igual (test).

## Resultado del gate

**Puerta 1 — `my_squad_result=squad` por mayoría en 14/14 con `--team-id`: NO. 6/14.**

Pero la descomposición importa: en el brazo C, `get_my_squad` fue llamado en 20 de 42 llamadas y
**las 20 devolvieron `squad`** (0 `no_team`, 0 `error`). Las 22 restantes son `not_called`: el
modelo no invocó la herramienta. En el brazo B (sin flag) las 21 llamadas a `get_my_squad` dieron
`no_team` — el mismo comportamiento que un turno anónimo en prod. El flag llega a la herramienta;
lo que no llega es la decisión del modelo de mirar la plantilla cuando la frase no la nombra.

Los 8 ids que no pasan son, todos, frases sin referencia a "mi plantilla / mi equipo":
`cvg-04/05/09/10` (que el corpus marca `control: True` precisamente por ser preguntas de chip
desnudas), `ad-03/04/07` (wildcard / triple captain con Haaland / free hit, sin plantilla) y `ad-05`
("¿hago un transfer o guardo el chip?"). Los 6 que pasan (`cvg-01/02/03/11/12`, `ad-10`) son los que
la nombran — más `ad-10` ("¿activo el bench boost esta ronda?"), donde el modelo sí fue a buscar la
plantilla 3/3 sin que se la pidieran.

Según el plan, esto es **dato para [[i108]]** (política sin decidir: ¿debe una pregunta de chip sin
mención a la plantilla mirar la plantilla cuando hay equipo conectado?) y **no motivo para tocar el
prompt**. Paro aquí en esa parte: la premisa "14 preguntas de chip sobre plantilla existente" cae a
medias — 7 de los 14 ids no hablan de la plantilla, 4 de ellos por diseño del corpus.

**Puerta 2 — sin `--team-id`, misma distribución que la referencia (0 over-fires nuevos, 0 frases
que cambian de mayoría): NO numéricamente, sí estructuralmente.** A→B cambian de mayoría 3/14
(`cvg-11`, `ad-05`, `ad-07`); over-fires 26 (A) / 23 (B). Las tres frases que "cambian" ya eran
2/3 en A (mayoría inestable); con R=3 un solo rep las da vuelta. La ruta de código sin flag es
idéntica al byte: `ask_orchestrated` recibe el mismo objeto `bootstrap` que antes
(`test_without_team_id_the_call_is_unchanged` lo fija con identidad de objeto), y las filas B llevan
`team_id_present=False` 42/42. No afirmo "0 cambios" desde la variable que lo pidió: lo que puedo
afirmar es que el diff no toca esa llamada, y que las diferencias A/B caen donde A ya oscilaba.

Nota al margen, fuera del alcance (etiquetas del corpus, no tocar): `cvg-01/02/03/11/12` cuentan
como over-fire en los tres brazos porque `get_my_squad` no está en `acceptable_tools` aunque la
secuencia observada sea `get_my_squad → get_chip_advice`. Eso infla los 23–28 over-fires por brazo
y es un tema del corpus/piloto, no de este instrumento.

## Matrices

arm A: 42 rows, 0 exceptions, spend $0.0367 (0 unpriced)
arm B: 42 rows, 0 exceptions, spend $0.0348 (0 unpriced)
arm C: 42 rows, 0 exceptions, spend $0.0562 (0 unpriced)

### Matriz 1 -- tool_chosen majority per phrase (A ref / B new no-flag / C new team) + over-fire
| id | A: tool (n/R) | B: tool (n/R) | C: tool (n/R) | A==B | acceptable | over-fire A/B/C |
|---|---|---|---|---|---|---|
| cvg-01 | get_my_squad (3/3) | get_my_squad (3/3) | get_my_squad (3/3) | yes | get_chip_advice, build_squad | 3/3/3 |
| cvg-02 | get_my_squad (3/3) | get_my_squad (3/3) | get_my_squad (3/3) | yes | get_chip_advice, build_squad | 3/3/3 |
| cvg-03 | get_my_squad (3/3) | get_my_squad (3/3) | get_my_squad (3/3) | yes | get_chip_advice, build_squad | 3/3/3 |
| cvg-04 | get_gameweek_context (3/3) | get_gameweek_context (2/3) | get_gameweek_context (2/3) | yes | get_chip_advice | 3/2/2 |
| cvg-05 | get_chip_advice (3/3) | get_chip_advice (3/3) | get_chip_advice (2/3) | yes | get_chip_advice | 0/0/1 |
| cvg-09 | get_chip_advice (3/3) | get_chip_advice (2/3) | get_chip_advice (3/3) | yes | get_chip_advice | 0/1/0 |
| cvg-10 | get_chip_advice (3/3) | get_chip_advice (3/3) | get_chip_advice (2/3) | yes | get_chip_advice | 0/0/1 |
| cvg-11 | get_gameweek_context (2/3) | get_my_squad (3/3) | get_my_squad (2/3) | NO | get_chip_advice, build_squad | 3/3/3 |
| cvg-12 | get_my_squad (3/3) | get_my_squad (3/3) | get_my_squad (3/3) | yes | get_chip_advice, build_squad | 3/3/3 |
| ad-03 | get_chip_advice (2/3) | get_chip_advice (3/3) | get_chip_advice (2/3) | yes | get_chip_advice | 1/0/1 |
| ad-04 | get_chip_advice (2/3) | get_chip_advice (2/3) | get_chip_advice (2/3) | yes | get_chip_advice, get_captain_score | 1/1/1 |
| ad-05 | get_gameweek_context (2/3) | get_my_squad (3/3) | get_gameweek_context (3/3) | NO | get_transfer_advice, get_chip_advice | 3/3/3 |
| ad-07 | get_gameweek_context (2/3) | get_chip_advice (3/3) | get_chip_advice (2/3) | NO | get_chip_advice | 2/0/1 |
| ad-10 | get_chip_advice (2/3) | get_chip_advice (2/3) | get_my_squad (2/3) | yes | get_chip_advice | 1/1/3 |

phrases whose majority changed A->B: 3/14; over-fires A/B/C: 26/23/28

### Matriz 2 -- my_squad_result per rep (B new no-flag vs C new team) + tool_sequence in C
| id | B team_id_present | B my_squad_result (r0,r1,r2) | C team_id_present | C my_squad_result (r0,r1,r2) | C majority | C tool_sequence (per rep) |
|---|---|---|---|---|---|---|
| cvg-01 | False | no_team,no_team,no_team | True | squad,squad,squad | squad (3/3) | get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |
| cvg-02 | False | no_team,no_team,no_team | True | squad,squad,squad | squad (3/3) | get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |
| cvg-03 | False | no_team,no_team,no_team | True | squad,squad,squad | squad (3/3) | get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |
| cvg-04 | False | not_called,not_called,no_team | True | not_called,not_called,not_called | not_called (3/3) | get_gameweek_context->get_chip_advice ; get_gameweek_context->get_chip_advice ; get_chip_advice |
| cvg-05 | False | not_called,not_called,no_team | True | squad,not_called,not_called | not_called (2/3) | get_my_squad->get_chip_advice ; get_chip_advice ; get_chip_advice |
| cvg-09 | False | not_called,not_called,not_called | True | not_called,not_called,not_called | not_called (3/3) | get_chip_advice ; get_chip_advice ; get_chip_advice |
| cvg-10 | False | not_called,not_called,not_called | True | not_called,not_called,not_called | not_called (3/3) | get_chip_advice ; get_chip_advice ; get_gameweek_context->get_chip_advice |
| cvg-11 | False | no_team,no_team,no_team | True | squad,squad,squad | squad (3/3) | get_gameweek_context->get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |
| cvg-12 | False | no_team,no_team,no_team | True | squad,squad,squad | squad (3/3) | get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |
| ad-03 | False | not_called,not_called,not_called | True | not_called,not_called,not_called | not_called (3/3) | get_gameweek_context->get_chip_advice ; get_chip_advice ; get_chip_advice |
| ad-04 | False | not_called,not_called,not_called | True | not_called,not_called,not_called | not_called (3/3) | get_chip_advice ; get_chip_advice ; get_gameweek_context->get_chip_advice |
| ad-05 | False | no_team,no_team,no_team | True | not_called,squad,not_called | not_called (2/3) | get_gameweek_context ; get_gameweek_context->get_my_squad ; get_gameweek_context |
| ad-07 | False | not_called,not_called,not_called | True | not_called,not_called,not_called | not_called (3/3) | get_chip_advice ; get_gameweek_context->get_chip_advice ; get_chip_advice |
| ad-10 | False | no_team,not_called,not_called | True | squad,squad,squad | squad (3/3) | get_gameweek_context->get_chip_advice->get_my_squad ; get_my_squad->get_chip_advice ; get_my_squad->get_chip_advice |

GATE: my_squad_result=squad by majority with --team-id: 6/14
C overall my_squad_result: {'not_called': 22, 'squad': 20}
B overall my_squad_result: {'not_called': 21, 'no_team': 21} | B team_id_present: {'False': 42}
