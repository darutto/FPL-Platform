# Encargo — entradas de la puntuación de capitanía

**Para:** Codex · **Preparado:** 2026-09-03 · **Estado:** sin empezar
**Urgencia:** los slices 1, 2 y 3 se quieren HOY. El deadline de la jornada 3 es
mañana 2026-09-04 17:30 UTC y la pregunta que está llegando ahora mismo es
«¿le doy el triple capitán a Haaland?».

Cartas del board: **i56** (resolver de jornada), **i57** (ventanas de chip),
**i58** (el componente de minutos está vacío), **i59** (dirección: la fórmula de
4 pesos es un suelo). Todo lo de abajo está verificado contra código y contra la
API en vivo el 2026-09-03; los números son reproducibles, no estimaciones.

---

## El problema en una frase

La superficie de capitanía ya sabe **sobre quién y sobre cuándo** le preguntan
(eso lo arregló PR #195), pero las **entradas** con las que puntúa están rotas o
sin leer: apunta a una jornada terminada, ignora que el chip caduca, y su
componente de «minutos» no contiene minutos.

---

## Lo que este encargo SÍ decide y lo que NO

**SÍ.** Reparar entradas que demostrablemente no contienen la información que
declaran, y leer datos que ya descargamos y no miramos. Nada de esto inventa un
coeficiente.

**NO.** Añadir factores nuevos a la fórmula (penales como peso, carga de
calendario, xMins de Sportmonks), tocar los cuatro pesos, ni rediseñar el motor.
Eso es **i59** y necesita histórico y calibración. Si al ejecutar esto te apetece
«ya que estoy» meter penales en la puntuación: no. Va como eje visible en el
Slice 4, no como sumando.

---

## Hallazgo que cambia la forma del encargo — leer antes de planificar

**Reparar los minutos NO hace que Haaland suba.** Medido:

| jugador | % minutos | riesgo hoy | riesgo reparado | score hoy | score reparado |
|---|---|---|---|---|---|
| Cherki | 60% | 0.0 | 40.0 | 85.67 | **81.67** |
| B.Fernandes | 100% | 0.0 | 0.0 | 82.20 | 82.20 |
| Gakpo | 89% | 0.0 | 11.1 | 74.19 | 73.08 |
| M.Sangaré | 92% | 0.0 | 8.3 | 73.38 | 72.55 |
| Haaland | 100% | 0.0 | 0.0 | 71.10 | **71.10** |

    orden hoy        Cherki · B.Fernandes · Gakpo · Sangaré · Haaland
    orden reparado   B.Fernandes · Cherki · Gakpo · Sangaré · Haaland

La reparación corrige la inversión concreta —un jugador al 60% de minutos deja
de salir primero— y eso ya justifica hacerla. Pero **Haaland sigue último de
cinco**, porque su problema no son los minutos: es `form` (7.5) pesando el 40%
como puntos por aparición.

**Consecuencia para el diseño:** lo que evita hoy la idea equivocada NO es el
número, es **enseñar los factores** (Slice 4). Un usuario que pregunta por
Haaland tiene que ver «100% de minutos, penaltero, mismo partido que Cherki» y
no solo «71.1 contra 85.7». No cerréis el encargo declarando victoria porque el
orden cambió: si el Slice 4 no entra, el problema de producto sigue vivo.

---

## Reglas de no-colisión — leer antes de tocar nada

1. **`CAPTAINCY_SURFACE_HANDOFF.md` ya se construyó** (commit `17535d2`, PR #195).
   Sus tres ejes —tiempo, jugador, pool determinista— están en `main`. **No
   re-diagnosticar ni rehacer nada de ahí.** `player`, `gameweek` y `horizon` ya
   existen en `GET_CHIP_ADVICE_SCHEMA`.
2. **«Encargo 2 — respuesta dual» de ese mismo fichero sigue SIN EMPEZAR** y toca
   `tools.py` con `squad_context`. Si alguien lo arranca en paralelo, hay
   colisión en `tools.py`. Coordinar antes, no asumir.
3. **Zona de i46** (camino de síntesis de `orchestrator.py`, render de fallback en
   `final_response.py`): sigue prohibida. No arreglar de paso.
4. **Trabajar en worktree propio.** Nunca en un checkout compartido: hay sesiones
   paralelas y las colisiones de rama/stash son silenciosas.
5. En el árbol hay sin commitear `scripts/track_ep_next.py` y
   `data/captaincy_tracking/` (tracker de `ep_next`, trabajo del dueño). No
   commitearlos dentro de este encargo.

---

## Mapa de ficheros

| qué | dónde |
|---|---|
| Resolver de jornada | `packages/fpl-api-client/fpl_api_client/fpl_client.py` — `get_current_gameweek():171`, bucle `is_current` en `:187` |
| Derivación de entradas | `packages/fpl-tool-contract/fpl_tool_contract/scoring_core.py` — `_derive_base_scoring_inputs():203`, `_STATUS_RISK:24` |
| Entradas del asistente | `packages/fpl-grounded-assistant/fpl_grounded_assistant/scoring_shared.py` — `_derive_scoring_inputs():145` |
| Fórmula | `packages/fpl-captain-engine/fpl_captain_engine/captain_score.py` — `calculate_captain_score():65` |
| Consejo de chip | `packages/fpl-grounded-assistant/fpl_grounded_assistant/chip_advisor.py` — `_advise_triple_captain():276`, umbrales `:102`, regla de wildcard `:33` (docstring) y `:108` (constante) |
| Render de tarjeta | `packages/fpl-grounded-assistant/fpl_grounded_assistant/renderer.py` |
| Medición existente | `packages/fpl-grounded-assistant/scripts/measure_captain_pool_variance.py` (patrón de regla pre-registrada) |

---

## Slice 0 — congelar el antes (antes de tocar puntuación)

El Slice 3 cambia un ranking. Sin un antes registrado no se puede afirmar
después qué movió, y la regla de la casa es que la regla de decisión se escribe
**antes** de ver el resultado.

- Script de medición commiteado **sin cambios posteriores**, patrón de
  `measure_captain_pool_variance.py`.
- Bootstrap **congelado** con su SHA-256 en cada observación.
- Registrar, para el pool derivado completo: `web_name`, `minutes`, `starts`,
  `penalties_order`, `form`, `xgi_per_90`, `minutes_risk`, `captain_score`, y la
  posición en el ranking.
- Guardar en `field-notes/artifacts/` con fecha, como el resto.

**Pre-registrar la expectativa** (esto es lo que el Slice 3 debe confirmar o
refutar, escrito antes de ejecutarlo): los jugadores por debajo del 100% de
minutos disponibles bajan, los que están al 100% no se mueven, y **Haaland no
cambia de posición**. Si Haaland sube, algo más se tocó sin querer: parar y
mirar.

---

## Slice 1 — el resolver deja de apuntar a una jornada muerta · HOY

**Hoy:** `get_current_gameweek` devuelve el primer evento con `is_current` sin
comprobar `finished`. Entre el final de una jornada y el deadline siguiente
—unos tres días— la API mantiene `is_current=True` en la ya jugada. El fallback
a `is_next`, que está justo debajo, es inalcanzable.

**Observado el 2026-09-03:** «¿uso el triple capitán esta semana?» se contestó
sobre la **jornada 2, terminada**, recomendando a B.Fernandes con 88.2 — de un
partido ya jugado. Sin aviso.

**Cambio:** una jornada `finished` no puede ser el objetivo de una
recomendación. Sigue siendo la fuente de datos; deja de ser el destino.

**Criterios de aceptación:**
1. Con `is_current=True` **y** `finished=True` en GW2, y GW3 con deadline futuro,
   el resolver devuelve **3**.
2. Con una jornada en curso de verdad (`is_current=True`, `finished=False`),
   devuelve esa. Sin regresión.
3. Test que fije las dos formas del evento con bootstrap sintético, no con red.
4. Fin de temporada (ninguna sin terminar) sigue devolviendo `None`.
5. Revisar los demás consumidores de `get_current_gameweek` antes de tocarlo: no
   es solo capitanía. Enumerarlos en el PR.

---

## Slice 2 — leer las ventanas de chip que ya vienen en el bootstrap · HOY

**Hoy:** `bootstrap.chips[]` trae `start_event` / `stop_event` por chip.
`grep start_event|stop_event` sobre `packages/` da **cero resultados**.

    3xc  ventana 1  jornadas 1-19        3xc  ventana 2  jornadas 20-38
    wildcard / bboost / freehit          igual, dos ventanas

**Consecuencia:** el triple capitán de la ventana 1 **caduca en la jornada 19**,
no se guarda. Y la regla de wildcard de `chip_advisor.py:33` —«Unfavorable
(GW >= 29): late season, few gameweeks remain»— es hoy **falsa**: la 29 es el
principio de la segunda ventana con diez jornadas por delante.

**Cambio:**
- Leer las ventanas del bootstrap. **No hardcodear 19 ni 20**: el dato viene en
  la API y puede cambiar de temporada.
- Exponer en el payload del chip la ventana activa y **cuántas jornadas quedan
  antes de caducar**.
- Corregir la regla de wildcard para que razone dentro de la ventana vigente.

**Criterios de aceptación:**
1. El veredicto de `triple_captain` incluye ventana activa y jornadas restantes.
2. La regla de wildcard ya no llama «late season» a una jornada que es principio
   de ventana.
3. Ningún literal `19` / `20` / `38` nuevo en el código: todo sale de `chips[]`.
4. Si `chips[]` falta o viene raro, degradar sin romper y **decirlo**, no asumir
   temporada de ventana única en silencio.

---

## Slice 3 — que el componente de minutos contenga minutos · HOY

**Hoy:** `_derive_base_scoring_inputs` deriva `minutes_risk` de un lookup de
estado de **lesión** y nada más:

    _STATUS_RISK = {"a": 0.0, "d": 30.0, "i": 100.0, "s": 100.0, "u": 100.0}

Sano = 0.0. Cherki (108 min, 1 titularidad de 2) y Haaland (180 min, 2 de 2)
reciben **el mismo 0.0**. El peso del 10% no separa a nadie.

**Cambio:** el riesgo de minutos se deriva de los minutos, con datos que ya
están en el elemento del bootstrap (`minutes`, `starts`) y **sin inventar
coeficientes**: participación = minutos jugados sobre minutos disponibles del
equipo. El riesgo por lesión sigue mandando cuando es peor (un lesionado no se
«rescata» por haber jugado mucho antes).

**Criterios de aceptación:**
1. Dos jugadores sanos con participación distinta reciben `minutes_risk`
   distinto. Test que lo pinee con el caso Cherki/Haaland.
2. Un jugador lesionado o sancionado mantiene riesgo 100 aunque su participación
   histórica sea alta.
3. Arranque de temporada (0 partidos del equipo) no divide por cero ni marca a
   toda la liga como riesgo máximo.
4. El antes/después del Slice 0 queda registrado y **coincide con lo
   pre-registrado**: bajan los de participación parcial, Haaland no se mueve.
5. **No tocar los cuatro pesos.** Si al terminar te parece que el 10% se queda
   corto, eso es un hallazgo para i59, no un cambio de este PR.

---

## Slice 4 — enseñar el factor, no esconderlo · HOY si es posible

**Este es el que arregla el problema de producto.** Los slices 1-3 arreglan el
sistema; este arregla la decisión del usuario.

Con el Slice 3 hecho, Haaland sigue último de cinco por su `form`. Alguien que
pregunte «¿le doy el triple capitán a Haaland?» seguirá leyendo «tu candidato
71.1; mejor disponible 82.2» sin ninguna pista de que Haaland juega el 100% de
los minutos, tira los penaltis y juega el mismo partido que el que le recomiendan
por encima.

**Cambio:** que la respuesta y la tarjeta muestren, junto a la puntuación, los
factores que hoy están mudos:

- **riesgo de minutos** — participación y titularidades, en lenguaje llano
  («jugó 108 de 180 minutos posibles, 1 titularidad de 2»)
- **penales** — `penalties_order` ya está en el bootstrap
- que el triple capitán **multiplica también el riesgo**, no solo los puntos

**Reglas de diseño, no negociables** (vienen de i54, i55 y de la regla de marco
positivo):
1. Va como **eje visible al lado** de la puntuación, no sumado dentro de ella.
2. Nada de rojo-peligro ni lenguaje de alarma: se enmarca como oportunidad y
   contexto, igual que el resto del producto.
3. Si el orden y el factor se contradicen, **se dice**. El patrón de i51 e i54
   —dos partes del sistema afirmando cosas opuestas y el usuario leyendo la más
   visible— no se repite aquí.

**Criterios de aceptación:**
1. Preguntando por un jugador concreto, la respuesta nombra sus minutos y su
   condición de penaltero.
2. Un jugador con participación parcial en el top del ranking sale con su factor
   visible, no diluido en el número.
3. El texto no contradice a la tarjeta: mismo dato, misma cifra.

---

## Después de esto (NO en este encargo)

Queda anotado en **i59** y se decide con datos, no aquí:

- `form` pesa el 40% y son **puntos por aparición**, además topados: cualquier
  forma ≥ 10 puntúa igual. Es la distorsión dominante que queda después del
  Slice 3, y normalizarla es una decisión de modelo que exige backtest.
- **Sportmonks**: cuando entre, `xMins` de verdad y carga de calendario
  sustituyen a la participación aproximada de este encargo. El Slice 3 está
  pensado para ser **reemplazable**, no para quedarse: aislar la derivación en
  un punto único para que enchufar la fuente buena no sea una cirugía.
- **Pesos aprendidos** en vez de escritos a mano: destino, no siguiente paso.
  Exige histórico propio de predicción contra resultado — justo lo que empieza a
  acumular el tracker de `ep_next`.

La regla que sobrevive a todo esto: cada factor nuevo entra **como eje visible
antes que como sumando escondido**, y justifica su sitio contra resultados
pasados, no contra la intuición de quien lo propone.

---

# Addendum — trabajo pendiente del chat de superficie (2026-09-03)

Escrito desde la otra conversación, la que produjo `CAPTAINCY_SURFACE_HANDOFF.md`
y los PR #195 y #200. Todo lo de aquí está verificado contra código, contra la
API en vivo o contra producción.

## Corrección a la regla de no-colisión nº 2 — IMPORTANTE

Ese apartado dice que «Encargo 2 — respuesta dual sigue SIN EMPEZAR». **Ya no.**
Se construyó y **se fusionó en `main` el 2026-09-01 vía PR #200**.

> **Cómo verificarlo, porque el SHA confunde.** #200 entró por *squash*: el commit
> de la rama (`df45938`) **no** es ancestro de `main`, y comprobarlo así hace
> parecer que el trabajo no está. El commit de fusión es `2d98aab`. La
> comprobación que no engaña es por contenido:
>
>     git cat-file -e origin/main:packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_dispatch.py
>     git show origin/main:packages/fpl-tool-contract/fpl_tool_contract/tools.py | grep -c squad_player_ids
>
> Ambas dan positivo sobre `origin/main` (23 coincidencias en `tools.py`). Si tu
> checkout no lo tiene, está por detrás de `origin/main` — no es que falte.

Lo que eso significa para quien planifique:

- `tools.py` ya lee la plantilla: `owned`, `squad_source`, `squad_excluded`, y el
  pool derivado es `top 12 global ∪ propios elegibles`.
- Existe una costura nueva, `fpl_grounded_assistant/tool_dispatch.py`, que
  resuelve la plantilla deterministamente y la baja como ids. `orchestrator.py`
  importa `run_tool` de ahí — una línea, y el paso a través es exacto para todo
  lo que no sea un ranking derivado.
- **La colisión en `tools.py` ya no es hipotética: es real.** Cualquier lane que
  toque ese fichero parte de la versión con bloques A/B.

## Prerrequisito que el Slice 4 no nombra

El criterio de aceptación 3 del Slice 4 dice «el texto no contradice a la
tarjeta». **Hoy no hay texto**: `MessageList.tsx:180` descarta `final_text` en
cuanto hay tarjeta.

La razón está escrita en el propio fichero: la prosa duplicaba la tarjeta, y
envolverla en burbuja creaba una «caja doble» que el dueño rechazó
(feedback 2026-06-12). De esos dos motivos **solo el segundo sigue vigente** — la
prosa de hoy aporta juicio, no duplica. Y `RankingTable.tsx` documenta en su
cabecera que se renderiza *"beneath final_text"*: la tarjeta siempre esperó tener
texto encima.

**Sin deshacer esa supresión, el Slice 4 no puede cumplirse.**

### Diseño ya decidido

Tres direcciones maquetadas y una elegida por el dueño. Lienzo:
https://claude.ai/code/artifact/5e50201a-eb9d-45ea-ba15-e5c5dc5b7220

**Elegida: veredicto integrado.** Una sola caja, sin burbuja, con:

1. Banda de **veredicto** arriba: conclusión en una línea, y el matiz debajo.
2. Las listas como **secciones dentro de la misma tarjeta** (cabeceras, no cajas
   anidadas — eso es lo que evita la caja doble).
3. Pie plegable **«Por qué esta recomendación»** — nunca «por qué este orden»: el
   orden se rompe con dos listas, una decisión no.
4. **Notas ancladas como excepción, no como anotación de todo.** Solo donde el
   ranking engaña: un jugador con propiedad alta hundido, un `evitar` colado
   arriba. Una fila sin nota significa «aquí no hay sorpresa».

**Reservado para preguntas con nombre propio:** cuando el usuario pregunta por un
jugador concreto, la nota anclada a esa fila es el vehículo — ahí sí hay un
jugador del que hablar. Para preguntas abiertas manda el veredicto.

## Regla nueva y transversal — no revelar los pesos

**Nombrar los factores, nunca sus coeficientes.**

Detectado maquetando: el texto decía «la forma pesa un 40 % del cálculo». Eso
filtra el algoritmo. La versión correcta dice *«la forma es de lo que más mueve
la puntuación»* — informa igual y no publica el modelo.

Aplica **directamente al Slice 4**: la prosa la redacta el LLM con las señales
que le pasamos, así que si el prompt le entrega los pesos, los va a citar. Vale
para cualquier umbral interno, no solo para los cuatro pesos.

## Encargo 3 pendiente — abrir el pool, acortar listas, hipster real

Escrito completo en `CAPTAINCY_SURFACE_HANDOFF.md` («Encargo 3»). Resumen:

1. **Quitar el filtro de posición** de `captain_pool_elements` (hoy `element_type
   in (3,4)`). Decisión de producto del dueño: hay quien capitanea a un defensa y
   el sistema no debe decidirlo por él. Medido contra la API el 2026-08-29: sin
   ese filtro, **4 de los 12 primeros serían DEF/GKP** y el mejor defensa entraría
   **segundo**. No quedan sepultados — el 80 % de la puntuación es ciega a la
   posición.
   - Efecto colateral bueno: `squad_excluded` deja de llenarse de
     `not_eligible_position` y pasa a contener solo lo accionable.
   - **Requiere mostrar la posición en la tarjeta**, o un portero será
     indistinguible de un delantero.
2. **Listas cortas**: 3 + 1 hipster de tu plantilla, 5 + 1 global. El recorte es
   de **presentación**: el payload sigue cuadrando los 15, que costó un ciclo de
   review construir.
3. **Hipster por propiedad, no por el tier actual.** Trampa verificada: el tier
   `differential` de hoy es una banda de puntuación, no propiedad —
   `captain_tiers.py` lo declara en su cabecera («no ownership data»). Sacar el
   hipster de ahí devolvería el jugador **peor puntuado**. Usar
   `selected_by_percent`, que ya viaja en el cliente y el tier ignora.

## Dos cartas de instrumentación

**i53 · `pool_source` no llegó al contrato.** Se añadió en #195 para auditar de
dónde sale una respuesta, pero vive solo en `renderer.py` eligiendo una frase. Y
esa frase **solo aparece cuando responde el renderer determinista**: en cuanto la
síntesis funciona y el LLM redacta, desaparece. Verificado en producción. La
auditabilidad depende de que el LLM falle. Llevarlo al contrato, con `pool_size`
y `squad_source`.

**i52 · medir cada cuánto el modelo manda su propia lista.** El pool determinista
solo corre si el modelo omite `candidates`, y eso se le pide por la descripción
del schema — persuasión, no obligación. Dos observaciones en producción, una de
cada tipo: **n=1 cada una, no es una tasa**. La sonda existe
(`scripts/measure_captain_pool_variance.py`). **Bloqueada por i53**: hoy habría
que parsear castellano para contarlo.

> No atribuir la diferencia entre esas dos observaciones a ninguna causa. El
> modelo es no determinista —el Slice 0 de #195 midió 7 listas distintas en 10
> turnos idénticos— y en esta línea de trabajo ya se dieron por buenas cuatro
> explicaciones que resultaron falsas.

---

# Cómo repartirlo en un enjambre

El mapa de ficheros no basta para paralelizar esto. Hay **dos colisiones que no
se ven leyendo qué fichero toca cada slice**, y una de ellas hundiría el trabajo
en silencio.

**Colisión semántica, no de fichero.** El Slice 1 cambia a qué jornada apunta el
resolver. Eso no choca con nadie en el `diff`, pero cambia el resultado esperado
de casi todos los tests de los demás. Si dos lanes construyen sobre resolvers
distintos, ambos pasan en local y se contradicen al fusionar.

**Colisión de fichero real.** El Slice 3 y el Encargo 3 tocan los dos
`scoring_core.py` — `_derive_base_scoring_inputs` uno, `captain_pool_elements`
el otro. Funciones distintas, mismo módulo: se resuelve serializando, no rezando.

## Olas

**Ola 0 — en solitario, antes que nada.**
Slice 0 (congelar el antes) y **Slice 1** (resolver de jornada). Nadie más
arranca hasta que esto esté en `main`. Todos los demás parten de ahí.

**Ola 1 — cuatro lanes en paralelo, ficheros disjuntos.**

| lane | trabajo | ficheros propios |
|---|---|---|
| **A** | Slice 2 · ventanas de chip | `chip_advisor.py` |
| **B** | Slice 3 · minutos reales | `scoring_core.py` (`_derive_base_scoring_inputs`) |
| **C** | coexistencia prosa + tarjeta | `MessageList.tsx` |
| **D** | i53 · `pool_source` al contrato | `final_response.py`, `types.ts` |

Lane C es el más aislado de todo el encargo: un fichero que nadie más toca, y
desbloquea el criterio 3 del Slice 4. Puede arrancar sin esperar a nada.

**Ola 2 — depende de la 1.**

| lane | trabajo | espera a | por qué |
|---|---|---|---|
| **E** | Encargo 3 · abrir pool, listas cortas, hipster | **B** | mismo módulo |
| **F** | Slice 4 · enseñar el factor | **C** y **D** | necesita que exista texto y que los campos viajen |

**Ola 3.**
Lane **G** — la sonda de i52. Va la última a propósito: contar `caller` frente a
`derived` exige que i53 (lane D) esté fusionado, o habría que parsear prosa en
castellano.

## Reglas para el enjambre

1. **Un worktree por agente. Nunca un checkout compartido.** Hay sesiones
   paralelas vivas en este repo y las colisiones de rama y de stash son
   silenciosas: los dos agentes creen que van bien.
2. **Nadie toca `roadmap-board/data.json`.** Está en disputa entre sesiones. Si
   un lane necesita carta, que la pida.
3. **Zona de i46 prohibida** — camino de síntesis de `orchestrator.py` y render
   de fallback en `final_response.py`. El lane D toca ese fichero pero **solo**
   los campos del payload; el fallback no se roza.
4. **Regla de decisión escrita antes de medir.** Cualquier lane que mida escribe
   su criterio dentro del script antes de la primera llamada, como en i41, i44 y
   el Slice 0 de #195. Un número que se interpreta después de verlo no decide
   nada.
5. **Ningún lane declara victoria por su propio test.** El aviso del encargo vale
   para todos: el orden puede cambiar y el problema de producto seguir vivo.
6. **Un `N passed` local no prueba nada sobre CI**, en ninguna dirección.
   Verificar sobre checkout limpio antes de afirmar verde.
7. **Nunca revelar coeficientes** en nada que vea el usuario — regla del
   addendum, aplica sobre todo al lane F.

## El riesgo de fusión que hay que vigilar

Los lanes **B**, **E** y **F** cambian los tres, por caminos distintos, **qué
jugadores salen y en qué orden**. B repara los minutos, E abre el pool a
porteros y defensas, F cambia lo que se enseña de cada uno.

Fusionados de uno en uno cada cual parece correcto. Juntos pueden producir una
lista que nadie diseñó — por ejemplo un portero con participación parcial
subiendo por encima de un delantero. **Después de la última fusión hay que mirar
la lista completa una vez, con ojos de producto y no de test.**

---

# Corrección al reparto — brecha de paridad del resolver (hallazgo de Codex)

**El Slice 1 es más grande de lo que dice su enunciado, y esto cambia la ola 0.**

`scoring_core.py` **repite el selector de jornada**: tiene su propio
`if event.get("is_current")` en `captain_time_context()` (línea 78 en
`origin/main`), independiente de `get_current_gameweek()` en `fpl_client.py`.

Arreglar solo `fpl_client.py` dejaría las puntuaciones y el consejo de chip
apuntando igualmente a la jornada terminada. El Slice 1 tiene que cerrar **los
dos caminos a la vez**, o no arregla nada de lo que se ve.

**Procedencia, para que no se repita:** ese resolver duplicado lo introdujo el
PR #195 — el mismo trabajo de superficie que produjo `captain_time_context`. La
review de aquel PR comprobó que el *ranking* tuviera una sola fuente
(`captain_pool_elements`) y **no comprobó que la resolución de jornada también la
tuviera**. Es un caso más de la clase que el repo ya había auditado dos veces.

**Efecto sobre las olas:** la ola 0 pasa a tocar también `scoring_core.py`. Como
va en solitario no rompe el plan, pero significa que los lanes **B** (Slice 3) y
**E** (Encargo 3) rebasan sobre un `scoring_core.py` ya modificado. No arrancar
ninguno de los dos antes de que la ola 0 esté en `main`.

## Tres condiciones más antes de ejecutar, también de la review

1. **El Slice 3 necesita cerrar su contrato de denominador antes de tocar
   código.** «Participación = minutos jugados / minutos disponibles del equipo»
   no tiene fuente explícita para el denominador. Inferirlo del número de jornada
   falla en dobles, blancos y aplazamientos, y penalizaría en silencio a un
   fichaje reciente como si hubiera perdido minutos — que es justo la clase de
   recomendación engañosa que este encargo existe para eliminar. Decidir la
   fuente **y qué hacer cuando no sea fiable** antes de implementar.
2. **El Slice 2 debe devolver «ventana activa» y «jornadas restantes» como campos
   del contrato, con degradación explícita.** Hoy `chip_advisor.py` mantiene el
   corte fijo `GW >= 29`.
3. **La expectativa del Slice 0 sobre Haaland es una comprobación del snapshot
   congelado, no un invariante de producto.** Si alguien la lee como «Haaland no
   debe moverse nunca», bloqueará cambios correctos.

## Y una advertencia sobre el verde de partida

La corrida base dio **89 tests en verde** en las suites de resolución de jornada,
superficie de capitanía y contrato de herramientas. Ese verde **no cubre el caso
`is_current=True` y `finished=True`**, que es exactamente el que este encargo
cambia.

O sea: la suite actual no puede detectar el defecto ni confirmar su arreglo. El
primer commit del Slice 1 debería ser el test que falla.

