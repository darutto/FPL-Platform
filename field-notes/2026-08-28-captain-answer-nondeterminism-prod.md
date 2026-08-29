---
title: "Capitanía en producción — tres respuestas distintas a la misma pregunta, y un consejo de chip que contesta otra pregunta"
found_via: user reported the answer differed between phone and PC; the phone/PC framing turned out to be wrong. Follow-up on a triple-captain question surfaced a second, unrelated cluster.
captured: 2026-08-28
relevant_to: [orchestrator, contracts, ui, gw-resolution, chips, scoring]
status: new
---

## What prompted this

En producción (`app.benditofantasy.com`), la misma pregunta en español —
**«¿A quién debería dar el brazalete?»** — devolvió respuestas radicalmente
distintas en intentos sucesivos, incluyendo una que no responde la pregunta:
un volcado del estado de la jornada.

Las tres primeras hipótesis fueron **falsas**, y vale la pena dejarlas escritas
porque cada una parecía obvia con los datos que había en ese momento:

1. **«es el caché»** — el único `304` de la sesión era del documento HTML
   `/chat`. Todas las respuestas del asistente van por `POST /api/proxy` y
   todas volvieron `200` con `X-Vercel-Cache: MISS`. Nunca hubo caché en juego.
2. **«es el `squad_context: null`»** — descartada en ambas direcciones: **sin**
   plantilla salió la respuesta buena, y **con** plantilla cargada salió la
   degradada.
3. **«es un bug de mobile»** — el fallo se reprodujo en la PC, misma sesión,
   un `F5` de diferencia.

Todas las capturas de red vienen de la sesión en vivo del 2026-08-28.

---

## Findings

### 1. La misma pregunta produce al menos tres respuestas distintas en prod — severity: high

**What happens:** cuatro turnos capturados sobre `POST /api/proxy`, todos
`200` y `X-Vercel-Cache: MISS`:

| turno | payload enviado | respuesta |
|---|---|---|
| **A** | `squad_context: null`, `team_id: null` | `outcome: ok`, `intent: rank_candidates`, `llm_used: true` — 3 candidatos: Saka 79.67, Ødegaard 77.72, Gakpo 72.5 |
| **B** | `question: "/capitan"` (sin argumento) | `outcome: needs_clarification`, `supported: false`, `llm_used: false`, `suggestions: null` |
| **C** | `squad_context: {itb: 5, chips_remaining: [...]}`, `team_id: 68643` | `outcome: ok`, `intent: rank_candidates` — 8 candidatos: Hinshelwood 85.0 `[differential]`, Ødegaard 77.72, Lewis-Potter 76.9, M.Sangaré 72.56, Gakpo 72.5, Dewsbury-Hall 70.9, Stach 69.5, Tavernier 60.8 |
| **D** | misma pregunta que A y C | `Jornada actual: GW1 (finished). Próxima jornada: GW2 (deadline: 2026-08-28T17:30:00Z).` en bubble genérico, pill `IA ACTIVA` + `Seguir conversación →` |

**Evidence:** A y C son respuestas JSON completas capturadas del panel Response.
D se capturó como screenshot de la UI; su JSON **no** se capturó (ver *Open
questions*). D se reprodujo **en teléfono y en PC**, y en la PC ocurrió a un
`F5` de distancia de C, misma sesión y mismo prompt.

El usuario reportó además una **quinta variante** no capturada: una tarjeta de
jugador único para Saka, como si hubiera pedido `/capitan saka`.

**Why it happens:** varianza de muestreo del LLM al elegir herramienta. Mismo
input, misma sesión, distinta elección de herramienta por turno. No es estado
de cliente, no es red, no es contexto de usuario.

**Fix direction:** ver finding 2 — el arreglo no está en el turno, está en la
descripción de schema que atrae la elección equivocada.

---

### 2. El fallo D es el atractor `get_gameweek_context`, ahora observado en producción — severity: high

**What happens:** el orquestador elige `get_gameweek_context` en vez de la
herramienta de ranking de capitán.

> **Corrección importante, escrita después de contrastar con el board.** La
> primera versión de esta nota decía que *elegir la herramienta equivocada* era
> lo que producía el volcado de texto. **Eso es falso desde el PR #160.** La
> carta `i35` registra que, verificado en producción el 2026-08-24, el modelo
> **seguía** eligiendo `get_gameweek_context` en vez de `get_chip_advice` y aun
> así **escribía una respuesta útil**: «arreglamos que no contestara; falta que
> consulte lo correcto». Así que la elección equivocada y el volcado crudo son
> **dos fallos independientes** que aquí ocurrieron juntos. Este finding es solo
> el primero; el volcado es el finding 3.

**Evidence:** el string de D coincide con la salida ya registrada de esa
herramienta en
[`2026-08-18-agentic-loop-experiment.md:362`](2026-08-18-agentic-loop-experiment.md) —
`Jornada actual: GW1 (pending). Próxima jornada: GW1 (deadline: ...)`, con
`get_gameweek_context` como herramienta registrada. Mismo formato, misma
herramienta, distinto GW.

> **Cuidado con esa fila.** Es una fila de arm A, y
> [`2026-08-22-tool-trace-blind-spot.md`](2026-08-22-tool-trace-blind-spot.md)
> demostró que las filas A/B publicaron `tool_calls_trace` vacío: lo único que
> sobrevive es `tool_chosen = executed[0]`, la **primera** herramienta de la
> ronda. Así que **no** se puede afirmar «fue la única herramienta llamada» —
> solo que fue la primera registrada, y que el texto de la respuesta es su
> salida literal. Lo segundo es lo que sostiene la coincidencia con D.

La matriz de enrutamiento ya lo tenía medido: **18 de 37 misroutes caen en
`get_gameweek_context`**, y se dispara con preguntas de *decisión* ancladas a
una jornada. Una pregunta de capitanía sobre la GW vigente es exactamente ese
perfil. El reporte y el JSONL crudo **no están en esta rama** — viven en
`measure/tool-routing-confusion`, commit `8487f76`
(`field-notes/2026-08-23-tool-routing-confusion-matrix.md` y
`field-notes/artifacts/tool-routing-observations-2026-08-23.jsonl` allí).

**Lo nuevo aquí no es el mecanismo, es la clase de evidencia.** Hasta hoy el
atractor estaba medido **offline**, sobre bootstrap congelado y llamando
`ask_orchestrated()` directo. Esta es la primera instancia **en producción, por
el path real, con una respuesta equivocada visible para el usuario**. Eso
debería mover la prioridad de la carta i38, que hoy está en «medido, falta
decidir».

**Fix direction:** la matriz ya argumentó dónde va el arreglo — apretar la
descripción de schema de `get_gameweek_context`, que termina en *"Use before
reasoning about next GW"*, una auto-invitación abierta que las demás
herramientas no defienden (contraste: `get_chip_advice` sí se defiende
explícitamente de `build_squad`). **No** es un cambio en el número de
herramientas; la matriz descartó el pruning amplio.

---

### 3. El volcado crudo es la caída de síntesis de `i46`, observada en producción — severity: high

**What happens:** la llamada de síntesis devuelve 200 **sin texto**, y el
orquestador cae a renderizar **solo la primera herramienta**. Como esa
herramienta era `get_gameweek_context`, el usuario recibe su salida literal.

**Evidence:** el camino está en el código, no inferido. En `orchestrator.py`
(origin/main), justo antes del bloque de render:

    _LOG.warning(
        "synthesis LLM call succeeded but returned no text for "
        "provider=%s; rendering first tool only", ...

y el comentario del paso 9 lo dice explícitamente: *"Render answer; determine
outcome from first tool's status. (Fallback only: the synthesis call itself
failed or returned no text above.)"*.

Eso es **exactamente** lo que describe la carta `i46` del board
(«La síntesis responde 200 sin texto y el usuario recibe un render pelado»),
encontrada de rebote midiendo `i41` el mismo 2026-08-28.

**Por qué NO es el hueco de `_TOOL_TO_INTENT`.** Sigue siendo cierto que
`get_gameweek_context` no tiene entrada en ese mapa (verificado 2026-08-28,
`grep` sin ocurrencias en `dispatcher.py`), y eso explicaría la **ausencia de
tarjeta**. Pero no explica el texto crudo: desde el PR #160 la síntesis es
incondicional para todo turno con ≥1 herramienta, y `i35` verificó en prod que
elegir mal la herramienta ya **no** impide redactar. El texto crudo requiere que
la síntesis no emita nada. Atribuirlo al mapa era mi error.

**Lo que este caso aporta a `i46`, y complica su hipótesis:** `i46` midió
`0/52` en preguntas de ranking y `3/9` en construcción de equipo, y concluyó
que se concentra *«donde el payload de herramienta es grande»*
(`select_players_within_budget`, `get_my_squad`). **`get_gameweek_context`
tiene uno de los payloads más pequeños del catálogo** — dos números y un
deadline. Si este turno fue efectivamente una caída de síntesis, entonces el
tamaño del payload **no** es la variable que la explica, o no es la única.
Merece entrar en el experimento pre-registrado que `i46` ya dejó escrito.

**Agravante ya registrado en `i46`, aquí confirmado:** el default es
`max_tokens: int = 1024` en la firma de `orchestrator.py`, y el servidor no lo
sobreescribe. La sonda de `i46` corrió a 2048, o sea el doble del presupuesto
real de producción.

**Where:** `orchestrator.py` (fallback «rendering first tool only» y el default
`max_tokens=1024`), `MessageList.tsx:277,306` (la firma visual `IA ACTIVA` +
`Seguir conversación →`).

**Fix direction:** no tocar nada todavía — `i46` ya tiene escrito el
experimento correcto (mismas preguntas a 1024 vs 4096, contando
`synthesis_turn=False`, regla decidida antes de correr). Este caso solo añade
un brazo: incluir una pregunta que dispare `get_gameweek_context`, para probar
si el tamaño de payload importa.

---

### 4. Ninguna compuerta de calidad ve el fallo — severity: high

**What happens:** el turno degradado vuelve marcado como éxito. La herramienta
corrió bien; simplemente era la herramienta equivocada, y eso ninguna capa lo
mide.

**Evidence:** el caso más limpio ya está registrado en el experimento del
18-ago, en `gemini / Q7 / repetición 1`
([línea 362](2026-08-18-agentic-loop-experiment.md)). **Q7 pregunta por
presupuesto, un lock-in de Haaland y comparar formaciones 4-5-1 contra 5-4-1.**
La respuesta registrada es el volcado `Jornada actual: GW1 (pending)...` — no
toca ni presupuesto ni formación. Se puntuó:

    outcome            ok
    Axis 1             substantive_answer
    catastrophic rate  0/3   (gemini / A baseline / Q7, tabla resumen)

Es decir: una respuesta que ignora por completo la pregunta pasó como
*sustantiva* y con tasa catastrófica cero. (Con `anthropic` la misma celda da
`3/3`, así que el juicio además **depende del proveedor del evaluador** — otra
razón para no confiar en esa señal.)

En los turnos buenos de esta sesión, los campos que existen para detectar
degradación (`review_passed: true`, `degraded: false`, `orch_outcome: "ok"`)
también salen positivos.

> **Matiz que le debo a `i35`/`i46`:** decir «no existe ninguna señal» sería
> falso. **`synthesis_turn` sí existe** y viaja en el `routing_trace` de
> producción desde el PR #160. El problema es de *superficie*: el
> `routing_trace` solo se vuelca en `debug` cuando se pide explícitamente, y la
> respuesta que recibe la UI trae `debug: null`. La señal existe y está apagada
> en el único sitio donde el fallo se ve. Eso es más barato de arreglar que
> inventar una señal nueva — y es también la razón por la que no pude verificar
> el turno D.

**Why it matters:** cualquier métrica construida sobre los campos que sí
publica la respuesta cuenta este turno como exitoso. Es un punto ciego
silencioso, no un fallo ruidoso — el mismo patrón que
[`2026-08-13-instruments-failing-silently.md`](2026-08-13-instruments-failing-silently.md)
identificó como factor común de las lecturas falsas: el instrumento no grita,
simplemente no mira.

**Fix direction:** dos cosas distintas, y conviene no mezclarlas. (a) Para el
volcado: exponer `synthesis_turn` en la respuesta, o al menos alarmar sobre él
en servidor — la señal ya se calcula. (b) Para la herramienta equivocada: algo
del estilo «¿la herramienta elegida pertenece a la familia del intent?», que
hoy no existe y es el hueco real.

---

### 5. `/capitan` sin argumento es un callejón sin salida — severity: med

**What happens:** el tab COMMANDS ofrece `/capitan`, pero invocarlo pelado
devuelve una petición de aclaración que la UI no puede ayudar a resolver.

**Evidence:** turno B — `outcome: needs_clarification`, `supported: false`,
`clarification_asked: true`, y crucialmente **`suggestions: null`**. El texto
devuelto además está en inglés en un producto Spanish-first: *"Are you looking
for captaincy advice or player rankings for this gameweek? Try asking 'who
should I captain?'"*.

`ChatShell` arma wizard a partir de `suggestions`; sin ellas no hay wizard
posible. Es una instancia nueva de la clase ya auditada en
`project_wizard_ambiguity_gaps` (6 de 19 retornos ambiguos no podían armar
wizard), y también del patrón «copy dirigido al modelo que se filtra al
usuario» que esa misma auditoría marcó.

**Fix direction:** poblar `suggestions` en ese retorno, o que el slash command
pelado no llegue al backend y abra el wizard en cliente.

---

### 6. `squad_context` llega pero no segmenta la respuesta — severity: med (gap de producto)

**What happens:** con la plantilla cargada, el ranking sigue devolviendo
jugadores que el usuario no tiene. La respuesta es útil a medias: no distingue
«mejores opciones globales» de «mejor opción dentro de tu plantilla».

**Evidence:** turno C llevó `team_id: 68643` y `squad_context` poblado, y
devolvió Hinshelwood, Lewis-Potter, M.Sangaré, Stach y Tavernier — el usuario
confirmó que no posee esos jugadores.

**Fix direction:** respuesta dual explícita. Es una feature, no una regresión —
`get_my_squad` ya existe desde PR #167 y es el insumo natural.

---

## Segundo cluster: el consejo de Triple Capitán

Turno posterior, misma sesión, plantilla ya cargada:

    payload   question: "le doy el triple capitan a haaland en la fecha 3?"
              squad_context: {itb: 5, chips_remaining: ["wildcard","triple_captain","free_hit"]}
              team_id: 68643

    chip      {chip: "triple_captain", recommendation: "conditions_favorable",
               gw: 2, signal_value: 79, signal_label: "top captain score",
               chip_unavailable: false}

    tarjeta   «Triple Capitán  [GW2]  Condiciones favorables — top captain score 79.0»

El enrutamiento aquí **es correcto** (`intent: chip_advice`, `chip:
triple_captain`). Los cuatro findings siguientes no son del orquestador.

Fixtures del Manchester City verificados contra la API en vivo el 2026-08-28:

| GW | partido | FDR (MCI) |
|---|---|---|
| 2 | MCI **(V)** en CRY | 3 |
| **3** | MCI **(L)** vs **COV** | **2** |
| 4 | MCI (V) en MUN | 4 |

Y los dos jugadores en juego: **Cherki** (MCI, £7.6m, forma 11.0) y **Haaland**
(MCI, £15.5m, forma 7.5).

---

### 7. `get_chip_advice` no acepta ni jornada ni jugador — severity: high

**What happens:** la pregunta pierde sus dos argumentos en la frontera de la
herramienta. Ni «Haaland» ni «fecha 3» tienen dónde ir.

**Evidence:** `GET_CHIP_ADVICE_SCHEMA` declara **una sola propiedad**, `chip`
(enum de 4), con `additionalProperties: False`. No hay parámetro de gameweek ni
de jugador. Y `_advise_triple_captain(bootstrap)` recibe **solo el bootstrap**:
llama `_score_outfield_players(bootstrap)` y toma `ranked[0]`, el máximo
**global**. De ahí sale Cherki, que gana por forma (11.0 vs 7.5).

**Where:** `tool_schema_registry.py:328-349`,
`chip_advisor.py:265` (`_advise_triple_captain`), `chip_advisor.py:122-130`
(el GW sale de `_get_current_gameweek`, nunca del usuario).

**Why it matters — el consejo sale al revés:** la recomendación fue *«guardaría
el Triple Capitán para una mejor oportunidad de Haaland, especialmente una
jornada doble o un rival claramente más débil»*. El rival claramente más débil
**es el de la fecha 3 que preguntó el usuario**: COV en casa, FDR 2, el mejor
fixture del City en la ventana GW2-GW4. El sistema evaluó la GW2 (CRY fuera,
FDR 3) y con eso le dijo que esperara a algo que ya tenía delante.

**No es un fallo del modelo.** El LLM no tenía parámetro donde poner «fecha 3».
Es la brecha *answer-shaped vs query-shaped* ya registrada en
[`2026-08-06-query-primitives-gap.md`](2026-08-06-query-primitives-gap.md),
en un sitio nuevo.

**Fix direction:** `gameweek` opcional en el schema y en `_advise_triple_captain`;
y si no se acepta, que la respuesta diga explícitamente «evalúo la GW actual»
en vez de presentar el veredicto como si respondiera la GW pedida.

---

### 8. La tarjeta omite de quién es su propio número — severity: high

**What happens:** la tarjeta muestra `top captain score 79.0` junto a una
pregunta sobre Haaland, sin decir en ningún sitio que ese 79 es de **Cherki**.
La lectura natural es que 79.0 es la puntuación de Haaland.

**Evidence:** el tool sí calcula `signals.top_player` (`chip_advisor.py`, dict
`signals`), pero el payload `chip` de `FinalResponse` no lo lleva: los seis
campos observados son `chip, recommendation, gw, signal_value, signal_label,
chip_unavailable`. `ChipCard.tsx:25` desestructura exactamente esos seis. El
nombre del jugador **no llega a la UI**.

A eso se suma el pill `GW{gw}` (`ChipCard.tsx:41-42`) mostrando **GW2** en
respuesta a una pregunta sobre la fecha 3, sin ninguna marca de que la jornada
pedida se descartó.

**Fix direction:** propagar `top_player` al payload `chip` y renderizarlo. Es
barato y convierte un número huérfano en un dato legible.

---

### 9. La tarjeta contradice al texto, y la tarjeta es lo que se ve — severity: high

**What happens:** el texto aconseja **no** usar el chip; la tarjeta muestra un
badge verde de **«Condiciones favorables»**. Dicen cosas opuestas.

**Evidence:** el texto dice *«no es un sí rotundo»* y *«guardaría el Triple
Capitán»*. La tarjeta sale de `recommendation: conditions_favorable`, que es
determinista: `top_score 79 >= _TC_FAVORABLE_THRESHOLD` (`= 75.0`,
`chip_advisor.py:94`, comparación en `:283`). Ese veredicto describe **que
existe un buen capitán disponible (Cherki)**, no que convenga triplicar a
Haaland en la fecha 3.

**Lo interesante del caso:** el LLM **rescató parcialmente** una herramienta que
contestó otra pregunta — se dio cuenta y matizó. La tarjeta tira el rescate y
enseña el veredicto crudo. Cuando tarjeta y texto discrepan, la tarjeta se lleva
la atención. Es exactamente la oportunidad perdida que señaló el usuario.

**Fix direction:** el badge debería reflejar el veredicto *sobre lo preguntado*,
no el estado interno del tool; mientras no exista argumento de jugador/GW
(finding 7), la tarjeta no debería afirmar «favorable» a secas.

---

### 10. El disclaimer de disponibilidad del chip es obsoleto y falso — severity: med

**What happens:** la respuesta dice *«No se ha podido verificar aquí la
disponibilidad de tu chip»* cuando el sistema **sí** la verificó.

**Evidence:** `chip_advisor.py` incrusta la frase en `advice_text` de forma
incondicional: `"Note: whether you still have this chip available is not known
to this system."`. Pero el payload de la petición llevaba
`chips_remaining: ["wildcard","triple_captain","free_hit"]`, y
`final_response.py:285` documenta `chip_unavailable` como *"True when chip not
in squad_context.chips_remaining"* (Fase 8e1). La respuesta volvió con
`chip_unavailable: false` — es decir, **se comprobó y estaba disponible**.

La frase se escribió antes de 8e1 y nadie la revisó al añadir la comprobación.
El LLM la repitió fielmente.

**Fix direction:** condicionar la frase a si llegó `squad_context`.

---

### Nota aparte: pareció más grounded de lo que estaba

El texto dice *«para el equipo de Haaland, el calendario ofensivo tiene
dificultad media 2,8/5»*, y suena a que analizó al City a propósito. No lo
hizo: ese `fixture_context` se construye para el **top player** (`chip_advisor.py`,
`build_fixture_context(..., team_id=top.get("team_id"), ...)`), que resultó ser
Cherki — también del City. Si el mejor capitán del momento hubiera sido Saka,
el mismo párrafo habría descrito los fixtures del Arsenal dentro de una
respuesta sobre Haaland, con idéntico tono de confianza.

Acertó por coincidencia de club, no por diseño. Vale registrarlo porque es
justo el tipo de salida que invita a concluir que el sistema entiende más de lo
que entiende.

---

## Open questions

- **Frecuencia real en producción: desconocida.** De ~5 turnos observados, 2 o
  3 salieron mal, pero N=5 sin control y con el observador buscando el fallo.
  La matriz de i38 midió 84% de acierto en la familia `gameweek_state`
  *offline*, con otro modelo y otro path. **No se puede extrapolar ese 84% a
  producción** — proveedor, modelo y prompt difieren.
- **El JSON del turno D no se capturó**, y aunque se hubiera capturado **no
  habría bastado**. El log de red se limpió con el `F5` (*Preserve log*
  desmarcado), pero el dato que decide entre finding 2 y finding 3 es
  `synthesis_turn`, que viaja en el `routing_trace` y **no** se publica en la
  respuesta que ve la UI (`debug: null`). Así que la atribución del volcado a la
  caída de síntesis es **la hipótesis principal, no un hecho medido**. Para
  cerrarla hace falta un turno con el volcado de `debug`/`routing_trace`
  activado, no solo *Preserve log*.
- **¿`squad_context` afecta el ranking en absoluto?** A (sin plantilla) devolvió
  3 candidatos y C (con plantilla) devolvió 8, pero son turnos distintos con
  varianza de por medio. No medido, y no se debe asumir a partir de estos dos
  puntos.
- **La quinta variante** (tarjeta única de Saka) no se capturó y no se pudo
  reproducir. Hipótesis sin evidencia: la misma ruleta cayendo en
  `get_player_snapshot`.
- ¿Cuántos de los otros misroutes de la matriz producen también volcado sin
  tarjeta? Los 13 tools sin mapeo del 12-ago y los destinos frecuentes de
  misroute se solapan al menos en `get_gameweek_context`; no se ha cruzado
  ambas listas.
