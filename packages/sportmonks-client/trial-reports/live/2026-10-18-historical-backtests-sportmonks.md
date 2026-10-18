# Backtests con Sportmonks de temporadas pasadas (2024-25 y 2025-26)

**Todos los resultados de este informe son DESCRIPTIVOS: la precondición de identidad preinscrita no se cumple en ninguna de las dos temporadas** (86,30 % en 2024-25 y 85,29 % en 2025-26; umbral 95 %). Ningún criterio de aprobado cuenta como superado ni como fallado. Las enmiendas posteriores al gate se informan por separado y tampoco cambian el veredicto (2025-26 llega al 94,04 %, a 5 jugadores del umbral).

**Actualización posterior (enmienda 4, ver la sección final):** tras la re-captura con nombre y fecha de nacimiento, **2025-26 sí cumple la precondición (97,21 %)**; 2024-25 sigue sin cumplirla (70,46 %). Los criterios de 2025-26 se evalúan como estaban escritos y siguen sin superarse. La lectura descriptiva de arriba se conserva tal como se entregó.

Encargo del revisor fpl-platform-22, bajo el visto bueno permanente de Leo (solo análisis, cero llamadas a Sportmonks; la captura la hizo el constructor de add-ons con 120 llamadas). Sin LLM. Escrito para: Leo y el revisor, para la decisión del 23 de octubre. El plan se subió antes de mirar ningún dato nuevo (`…-PLAN.md`, primer commit del PR) y las enmiendas están fechadas por commit.

## Resultado en una página

| Prueba | Resultado (descriptivo) | Criterio preinscrito |
|---|---|---|
| **Gate de identidad** | 86,30 % y 85,29 %. Con el puente por `code` (enmiendas 2 y 3): 2025-26 94,04 %, 2024-25 sin cambio (su almacén no tiene `code`). | Falla (< 95 %) |
| **H1** Detector de cambios de rol | Un rol nuevo persiste (≥2 de las 3 titularidades siguientes) el 40 % tras 1 titularidad, el 53–54 % tras 2 y el 57–64 % tras 3 (individuales). El adelanto frente a la señal de xGI de FPL es de unos 2 partidos, pero el control al azar da una frecuencia parecida. | No se cumple (0,644 y 0,571 < 0,75) |
| **H2** Relevo por hueco frente a la línea base FPL | La población comparable (hueco, ≤1 titularidad previa) mantiene 0,59 / 0,44 / 0,33 en 2025-26, a la par o por debajo de la regla FPL sobre las mismas alineaciones (0,65 / 0,46 / 0,38) y de #478 T3 (0,63 / 0,46 / 0,36). | No se cumple |
| **H3** Rotación tras Europa | A ≤3 días la caída es de −1 a −1,4 puntos con IC amplios: no concluyente. Exploratorio: tras eliminatorias a doble partido, −6 a −9 puntos con IC que excluyen 0. | No concluyente |
| **H4** M1 con Sportmonks contra M1 con FPL | M1-Sportmonks mejora el Brier de titularidad (−0,005 en 2025-26, −0,011 en 2024-25, IC excluyen 0). En minutos no es concluyente en 2025-26. La regla simple gana en minutos. | Parcial |

**Qué dice el conjunto.** Sportmonks añade información sobre titularidad (H4) y permite explicar (J, H1, H2 y A del informe anterior), pero estos datos no demuestran que anticipe: los cambios de rol individuales se revierten con frecuencia, los relevos por hueco no duran más que los relevos que llegan sin hueco claro, y el efecto de la rotación tras Europa solo se ve, de forma exploratoria, en las eliminatorias.

## Datos y límites

- **Captura** (local, git-ignorada; no hay datos crudos ni identificadores del proveedor en git): Premier League 2024-25 y 2025-26 completas (760 partidos terminados, 16.720 titulares, todos con posición detallada y casilla); partidos europeos de 7 clubes en 2024-25 y 9 en 2025-26 (elegidos por memoria por el constructor de add-ons; cobertura de posición del 90 % en 2024-25 en Europa); FA Cup (con alineaciones solo en 296 de 1.793 partidos), Carabao incompleta en 2024-25 y ausente en 2025-26.
- **Estados, fechas y bajas de la captura son los de la lectura del 18 de octubre**: todo lo que use `sidelined` es **retrospectivo**. No hay marca de tiempo por alineación en ninguna temporada pasada.
- **La posición cruda es una función exacta de formación, casilla y lugar del partido** (0 excepciones en 330 y 385 combinaciones). Es un hecho del once anunciado; el rol y la banda salen de `role-map-v3`, que es una estimación nuestra y no tiene «Defensive Midfield» (37 y 45 titularidades sin rol, excluidas).
- **Estados de participación (i156), en todas partes:** titular; `not_started` (entra de suplente); `did_not_play` (0 minutos o fuera de la convocatoria); `unavailable` (fila de baja que cubre el partido). Los `unavailable` no están convocados, así que en H4 no entra ninguna fila.
- **IC:** bootstrap por conglomerados (partido de equipo; equipo-temporada en H3), 2.000 remuestreos.

## Precondición de identidad y enmiendas (en el orden en que ocurrieron)

1. **Gate (enmienda 1).** Se reutiliza el emparejador del registro de identidades (`match_player`), con el ensamblado de candidatos y el cruce de clubes del trial. Diferencia declarada respecto a 2026-27: la captura pasada no trae nombre completo ni fecha de nacimiento, solo el nombre de alineación; ese nombre hace de nombre completo y conocido, la primera pasada va sin club, el cruce de clubes sale de los pares de la primera (20 de 20) y una segunda pasada repite los no resueltos con el club para que apliquen los niveles con club. Resultado: 2024-25, 485 de 562 jugadores FPL con minutos (86,30 %); 2025-26, 458 de 537 (85,29 %). Todos los sin emparejar son `no_candidate` por la forma del nombre (FPL guarda «David Raya Martín», la alineación «David Raya»). Sin corrección a mano.
2. **Enmienda 2** (escrita después del gate y antes de calcular H1 a H4): puente sin llamadas. Jugador de Sportmonks → elemento FPL de 2026-27 (emparejamiento del trial, revisado por Leo) → `code` estable de FPL → elemento de esa temporada, solo donde el almacén tiene `code` (2025-26 sí; 2024-25 no, en ninguna tabla). Con club en la fecha y posición: 2025-26 llegó al 92,36 %.
3. **Enmienda 3** (corrección pedida por el revisor): la posición de alineación contra el tipo de FPL no es un criterio de identidad, porque el rol de alineación es justo lo que se mide y excluye a quienes juegan fuera de su posición de FPL. Se retira. **Orden, sin adornos:** se escribió *después* de haber calculado ya la persistencia de H1 y una primera versión del adelanto (no se cumplió «antes de cualquier resultado de H1 a H4»); la persistencia de H1 no usa el emparejamiento y no cambia, y el adelanto se informa en las dos versiones. H2, H3 y H4 se calcularon después. Resultado: 2025-26, **94,04 %** (505 de 537): **falla por 5 jugadores**. 2024-25 sigue en 86,30 %. Quedan 32 sin emparejar (más minutos: Sánchez, Bernardo, Cucurella, S.Bueno, H.Bueno, A.Jimenez, J.Palhinha, Raúl, Gana, Mosquera, Mitoma, L.Paquetá, Rodrigo, Perri, Hee Chan…).
4. **Hallazgo lateral:** los 50 jugadores que la regla de posición había rechazado son exactamente los que juegan fuera de su posición de FPL: 33 centrocampistas de FPL con posición de delantero en la alineación (Gustavo Nunes, McAidoo, Odobert, Mundle, Alysson, Okafor, Talbi, Ndoye, Adli, Kluivert, Foden…), 12 defensas con posición de centrocampista (Gudmundsson…), 4 centrocampistas con posición de defensa (Miley, de lateral derecho) y 1 delantero con posición de centrocampista (Kroupi). Para 7 jugadores el tipo FPL de la temporada difiere del de 2026-27 con el mismo `code`.

**Cómo se arregla de forma limpia.** Volver a pedir las páginas de la liga con `lineups.player` (nombre completo y fecha de nacimiento): son unas 32 llamadas (16 páginas por temporada) y debería llevar la identidad a ~99 % como en 2026-27. Alternativa: jugadores por identificador, del orden de 30 llamadas. Necesita el visto bueno de Leo.

## H1. Detector de cambios de rol

**Definiciones (plan).** Unidad: serie de titularidades de liga de un jugador. Rol base R0: rol modal de sus 3 a 5 titularidades anteriores a la racha. Rol nuevo R1 distinto de R0. «Posible»: 1 o 2 titularidades consecutivas en R1; «confirmado»: 3. **Individual** (misma formación del equipo que en el partido anterior) separado de **por formación de equipo**. Persistencia: ≥2 de las 3 titularidades siguientes en R1 (estricta: las 3). Línea base «mismo rol que la última titularidad».

| | Posible (1 titularidad) | Posible (2) | Confirmado (3) |
|---|---|---|---|
| 2024-25 individual (n) | 0,397 [0,341, 0,455] (290) | 0,542 [0,443, 0,632] (120) | 0,644 [0,525, 0,759] (59) |
| 2025-26 individual (n) | 0,399 [0,337, 0,462] (281) | 0,528 [0,436, 0,616] (125) | 0,571 [0,457, 0,686] (70) |
| 2024-25 por formación de equipo | 0,335 | 0,515 | 0,567 |
| 2025-26 por formación de equipo | 0,381 | 0,701 | 0,821 [0,710, 0,922] (67) |

Exactitud del rol de la siguiente titularidad, individual (línea base contra detector): 2024-25, 0,466 / 0,592 / 0,714 contra 0,378 / 0,268 / 0,714; 2025-26, 0,500 / 0,592 / 0,679 contra 0,342 / 0,282 / 0,679. La línea base gana en «posible»; en «confirmado» coinciden por construcción.

**Criterio preinscrito** (persistencia de «confirmado» individual ≥ 0,75 con límite inferior ≥ 0,70, y mayor que «posible»): **no se cumple** (0,644 y 0,571). Un rol nuevo tras 1 o 2 titularidades persiste menos de la mitad de las veces; los cambios por formación de equipo persisten más que los individuales en 2025-26.

**Adelanto frente a la señal visible en FPL** (xGI/90 de los últimos 3 partidos ≥ +0,15 sobre los 6 anteriores, ≥150 minutos en cada ventana; jugadores emparejados: 83 % de los eventos en 2024-25 y 94 % en 2025-26 con la enmienda 3, 88 % con la 2). Entre los eventos con señal FPL en los 6 partidos siguientes (104 de 318 y 153 de 312): mediana de adelanto de 2 partidos; en el mismo partido el 33 % y el 30 %; al menos un partido antes el 67 % y el 70 %. **El control lo relativiza:** la señal FPL aparece en los 6 partidos siguientes en el 33,3 % de los jugadores elegidos al azar en 2024-25 (tras un cambio de rol, 32,7 %: igual) y en el 38,1 % en 2025-26 (tras un cambio, 49,0 %: unos 11 puntos más, IC binomial aproximado de 5 a 17, sin agrupar). Además, en el 16–22 % de los eventos la señal FPL ya era cierta antes de la alerta. Solo asociación.

## H2. Relevo por hueco frente a la línea base FPL (#478 T3: 60 / 43 / 33 %)

**Definiciones (plan).** Evento: un titular habitual (≥3 de sus 4 partidos previos y titular en el anterior) no es titular en m. Candidato de hueco: titular en m con el mismo rol y banda que el ausente y **la misma formación de equipo** (un hueco igual en otra formación no cuenta). Se excluyen los fichajes recién llegados (primer partido en convocatoria con ese club dentro de los 4 previos). Población (b): candidatos con ≤1 titularidad en los 3 partidos previos, la comparable con T3. Comparador (2): la regla FPL aplicada a las mismas alineaciones (≤1 titularidad previa, que no ocupan el hueco; sin «barato» porque Sportmonks no trae precio).

| 2025-26 (confirmación) | Mantiene 1 | 2 | 3 | n (1) |
|---|---|---|---|---|
| (a) Todos los candidatos de hueco | 0,704 [0,672, 0,737] | 0,586 [0,552, 0,620] | 0,480 [0,442, 0,515] | 803 |
| (b) Hueco, ≤1 titularidad previa | 0,591 [0,539, 0,644] | 0,442 [0,392, 0,494] | 0,330 [0,281, 0,384] | 430 |
| Comparador FPL sobre estas alineaciones | 0,653 [0,617, 0,689] | 0,461 [0,424, 0,497] | 0,375 [0,339, 0,410] | 839 |
| #478 T3 (proxy), 2025-26 | 0,634 | 0,457 | 0,364 | |
| (b) − comparador | −0,062 [−0,126, +0,001] | −0,019 [−0,083, +0,047] | −0,044 [−0,109, +0,017] | |
| (b) mantiene el mismo hueco | 0,516 | 0,365 | 0,264 | |

2024-25 (desarrollo), población (b): 0,504 [0,454, 0,558] / 0,328 [0,283, 0,377] / 0,257 [0,214, 0,302] (n=510); comparador 0,613 / 0,435 / 0,346; diferencia (b) − comparador −0,109 [−0,173, −0,043] / −0,108 [−0,163, −0,050] / −0,089 [−0,142, −0,033]; T3 de #478 para esa temporada 0,577 / 0,395 / 0,305.

**Por estado del ausente** (población b, mantiene 1 / 2 / 3). 2025-26: `did_not_play` 0,605 / 0,440 / 0,337 (n=256); `not_started` 0,563 / 0,441 / 0,312 (n=167); `unavailable` solo n=7. 2024-25: `did_not_play` 0,547 / 0,354 / 0,293 (n=236); `not_started` 0,468 / 0,314 / 0,214 (n=222); `unavailable` 0,462 / 0,269 / 0,269 (n=52). Las bajas son las de hoy y apenas cubren esas temporadas: sin lectura de baja registrada contra ausencia sin baja.

**Criterio preinscrito** (límite inferior del IC del hueco mayor que el límite superior de T3 en k=1, 2 y 3, y diferencia con el comparador con IC que excluye 0 en k=1 y 2): **no se cumple**. Conocer el hueco no mejora la continuidad del recién llegado sobre una regla FPL aplicada a las mismas alineaciones, y en 2024-25 la empeora. Solo (a), que incluye a habituales que cambian de hueco, supera las tasas de T3, pero no es la población comparable.

## H3. Rotación tras partidos europeos

**Definiciones (plan).** Habituales fijados antes del partido (≥75 % de titularidades en sus hasta 4 partidos previos, mínimo 3, y titular en el anterior). Exposición: partido de liga cuyo partido anterior del club, de cualquier competición, fue UCL, UEL o UECL con ≤3 días de descanso (principal) o ≤4 (secundaria). Control: partidos de liga del mismo equipo cuyo partido anterior fue de liga con ≥5 días. Diferencia por equipo-temporada, ponderada por n de exposición, IC por bootstrap de equipo-temporada. Solo hay 7 clubes con Europa en 2024-25 y 9 en 2025-26.

| | Exposición contra control (tasa de titulares) | Diferencia dentro del equipo | Partidos exposición / control |
|---|---|---|---|
| 2024-25, ≤3 días (principal) | 0,809 contra 0,823 | −1,40 pp [−6,45, +3,32] | 47 / 83 |
| 2024-25, ≤4 días | 0,806 contra 0,823 | −1,73 pp [−4,46, +1,61] | 82 / 83 |
| 2025-26, ≤3 días (principal) | 0,832 contra 0,834 | −0,87 pp [−6,39, +3,75] | 61 / 113 |
| 2025-26, ≤4 días | 0,809 contra 0,834 | −2,54 pp [−5,61, +0,38] | 99 / 113 |

Con los umbrales de #478 T2 («caída» = ≥5 puntos con IC que excluye 0; «sin efecto» = IC entero dentro de ±3): **no concluyente** en las dos temporadas. El efecto medio ronda −1 a −2,5 puntos, coherente con #478 T2 (−1,6).

**Exploratorio (no entra en el criterio; hipótesis de Leo como pregunta abierta).** Proxy de alto riesgo: el partido europeo anterior era una eliminatoria a doble partido, con ≤4 días de descanso. No es «rival de élite», que no se puede definir sin una lista de clubes que la captura no trae.

| | Eliminatoria (exposición) | Fase de liga o partido único |
|---|---|---|
| 2024-25 | 0,732 contra control 0,823: −9,32 pp [−18,98, −0,59] (29 partidos) | +1,84 pp [−0,65, +4,59] (53) |
| 2025-26 | 0,771 contra control 0,834: −6,12 pp [−10,86, −1,08] (35) | −0,73 pp [−4,44, +3,21] (64) |

Por competición, ≤4 días: UCL 2025-26 −4,12 pp [−7,10, −1,42] (55 partidos); UCL 2024-25 −1,35 [−4,77, +1,22]; UEL y UECL −2,12 [−6,52, +5,63] y −0,69 [−6,97, +3,71]. La caída de 6 a 9 puntos aparece tras las eliminatorias y no tras la fase de liga, en las dos temporadas, con IC que excluyen 0 (29 y 35 partidos); es compatible con la hipótesis, pero es una sola lectura con un proxy débil, sin ajustar por rival ni por la importancia del partido de liga y con el calendario de copas incompleto (el control puede incluir algún partido precedido por una copa que no vemos).

## H4. Regla simple, M1 con entradas de FPL y M1 con entradas de Sportmonks

**Diseño (plan).** Puntos de corte: partidos de liga desde el 4.º de cada equipo, sin muestreo. Lista fijada antes: jugadores con ≥1 titularidad de Sportmonks en sus hasta 6 partidos previos y fila en la alineación del partido, emparejados con FPL para que los tres vean las mismas filas. Objetivo común: titular y minutos de la alineación de Sportmonks. (1) Regla simple y (2) M1-FPL leen la serie de FPL (proxy ≥60 minutos donde no hay `starts`; congestión solo de liga); (3) M1-Sportmonks lee la alineación de Sportmonks y la congestión a 21 días con liga, copas nacionales (1,0) y europeas (1,25). Sin ajustar coeficientes.

| | Filas | Brier simple / M1-FPL / M1-Sportmonks (base) | MAE minutos simple / M1-FPL / M1-Sportmonks (base) |
|---|---|---|---|
| 2024-25 | 8.465 | 0,1696 / 0,1688 / **0,1583** (0,1971) | **20,82** / 24,53 / 24,27 (29,39) |
| 2025-26 | 9.652 | 0,1719 / 0,1691 / **0,1639** (0,2052) | **20,48** / 24,87 / 24,71 (30,73) |

Diferencias con IC 95 %. 2025-26: Brier M1-Sportmonks − M1-FPL −0,0052 [−0,0075, −0,0030]; MAE M1-Sportmonks − M1-FPL −0,157 [−0,360, +0,046]; Brier M1-FPL − simple −0,0028 [−0,0061, +0,0004]; MAE M1-FPL − simple +4,39 [+4,12, +4,67]; Brier M1-Sportmonks − simple −0,0080 [−0,0125, −0,0037]; MAE M1-Sportmonks − simple +4,23 [+3,86, +4,59]. 2024-25: −0,0105 [−0,0133, −0,0077]; −0,266 [−0,478, −0,067]; −0,0008 [−0,0037, +0,0021]; +3,72 [+3,45, +3,98]; −0,0114 [−0,0159, −0,0069]; +3,45 [+3,09, +3,82].

**Criterio preinscrito** (M1-Sportmonks mejor que M1-FPL en Brier y en MAE, IC que excluye 0, en 2025-26): Brier sí, MAE no (el IC incluye 0): **parcial**. Las entradas de Sportmonks mejoran la probabilidad de ser titular; apenas los minutos. La regla simple gana en minutos por unos 4. En #478, con FPL puro, M1 ganaba a la simple en titularidad; aquí M1-FPL queda a la par de la simple. La diferencia es que el objetivo es la titularidad real de Sportmonks y la serie FPL de 2024-25 usa el proxy de ≥60 minutos. No se ha aislado qué parte de la mejora de M1-Sportmonks viene de tener titularidades reales en lugar de un proxy y qué parte de la congestión con Europa y copas.

## Tercera comprobación: 2026-27 hasta hoy

Solo hay GW1 a GW7 y no se ha calculado nada con ellos, porque las definiciones preinscritas no caben: H1 «confirmado» exige 3 titularidades previas, 3 en el rol nuevo y 3 siguientes para medir la persistencia (9 titularidades, y hay 7 partidos); H2 con k=3 exige 4 partidos previos, el partido del evento y 3 siguientes (8 partidos). Para H3 el análisis equivalente de #475 (B) cuenta 11 partidos de liga tras Europa en 8 equipos. Se deja como informativa, como pedía el plan, sin criterios.

## Qué no se pudo hacer

- Cumplir la precondición de identidad (falla en las dos temporadas; 2025-26 por 5 jugadores). Se arregla con un re-fetch que necesita el visto bueno de Leo (~32 llamadas).
- Marca de tiempo por alineación y estado de baja por partido: todo lo que use `sidelined` es retrospectivo.
- Un «rival de élite» para el corte exploratorio de H3, y Carabao completa en las dos temporadas.
- Aislar de dónde viene la mejora de M1-Sportmonks en H4 (titularidades reales contra proxy, congestión europea).


## Actualización: re-captura con nombre y fecha de nacimiento (enmienda 4) y sensibilidad de H3

Escrita después de la entrega anterior. La enmienda 4 está en el plan y se subió antes de calcular ninguna tasa con los datos nuevos.

### Re-captura e identidad

Leo aprobó volver a bajar las páginas de la Premier de 2024-25 y 2025-26 con `lineups.player` (nombre, nombre de alineación y fecha de nacimiento), con un máximo de 40 llamadas. Se usaron **16** (8 por temporada, `per_page=50`; la primera, una sonda, ya devolvió 50 partidos y todas las filas con jugador y fecha de nacimiento). El token sale de la variable de entorno y no se imprime ni se guarda; contador persistente con tope duro de 40, parada ante cualquier respuesta distinta de 200, sin redirecciones; los ficheros crudos quedan en `trial-output/past_players/` (git-ignorado). La identidad se mide con el **procedimiento exacto del trial** (`fpl_side` de `trial_mapping.py`, primera y segunda pasada), un solo camino, sin el puente por `code`.

| | Jugadores FPL con minutos | Emparejados | Tasa | Precondición (≥95 %) |
|---|---|---|---|---|
| 2025-26 | 537 | 522 | **97,21 %** | **Se cumple** |
| 2024-25 | 562 | 396 | 70,46 % | Falla |

2025-26: `full_name_birth_date` 498, `surname_birth_date` 125, `display_name_birth_date` 28, `full_name_unique` 5. Quedan 15 sin emparejar, casi todos nombres compuestos o abreviados (Martinez, Buendía, Senesi, Mitoma, Chadi Riad, Alcaraz, Tanaka, Endo, Morato, Solanke, Taty, H.Bueno, Mosquera, S.Bueno, Hee Chan). 2024-25 falla porque el almacén de FPL de esa temporada **no tiene fecha de nacimiento** (166 sin emparejar por `fpl_birth_date_absent`): con el procedimiento exacto, ahí no hay nivel que lo compense, y queda peor que la ruta aproximada anterior (86,30 %). 2024-25 sigue siendo descriptiva; **la confirmación (2025-26) es válida.**

**Lectura tras la re-captura, 2025-26** (criterios tal como estaban escritos):
- **H1:** la persistencia de «confirmado» individual es 0,571 [0,457, 0,686], por debajo del 0,75: **no se cumple.** Con el emparejamiento nuevo todos los eventos individuales tienen jugador FPL (330 de 331). Señal FPL en los 6 partidos siguientes: 161; mediana de adelanto 2 partidos; frecuencia al azar 0,381 contra 0,488 tras un cambio de rol (como antes).
- **H2:** usa solo identificadores de Sportmonks, sin cambios: **no se cumple.**
- **H3:** sin cambios: **no concluyente** (y la sensibilidad de abajo lo confirma).
- **H4** (9.860 filas, 447 jugadores): Brier M1-Sportmonks menos M1-FPL −0,0055 [−0,0076, −0,0033]; MAE de minutos −0,156 [−0,361, +0,048]; MAE M1-FPL menos simple +4,36 y M1-Sportmonks menos simple +4,21. Brier sí, MAE no: **parcial**, igual que antes.

### Sensibilidad de H3 con el calendario completo de copas

Declarada como sensibilidad, no como prueba nueva, y sin llamadas. El constructor de add-ons completó la captura de la FA Cup y la Carabao de los 20 clubes (167 partidos únicos). La versión original no veía todos los partidos de copa, de modo que parte de los partidos de liga que usaba como control («el partido anterior fue de liga con 5 o más días de descanso») venían en realidad precedidos por una copa. Con el calendario completo, el control baja de 83 a 64 partidos en 2024-25 y de 113 a 88 en 2025-26. Las definiciones no cambian.

**(a) ¿Cambia el resultado principal tras Europa?** No: sigue sin ser concluyente, y las estimaciones se acercan a cero.

| Exposición | 2024-25 (original → completo) | 2025-26 (original → completo) |
|---|---|---|
| ≤3 días (principal) | −1,40 pp [−6,45, +3,32] → **+1,13 pp [−4,80, +5,99]** | −0,87 pp [−6,39, +3,75] → **−0,28 pp [−5,89, +3,81]** |
| ≤4 días | −1,73 [−4,46, +1,61] → +0,63 [−2,70, +4,22] | −2,54 [−5,61, +0,38] → −1,68 [−4,96, +1,30] |

**(b) ¿Se sostiene el efecto exploratorio de las eliminatorias a doble partido (≤4 días)?** Se debilita: se sostiene en 2025-26 y deja de excluir 0 en 2024-25.

| | 2024-25 (original → completo) | 2025-26 (original → completo) |
|---|---|---|
| Eliminatoria (29 y 35 partidos) | −9,32 pp [−18,98, −0,59] → **−6,66 pp [−17,29, +2,42]** | −6,12 pp [−10,86, −1,08] → **−5,34 pp [−10,04, −0,84]** |
| Fase de liga o partido único | +1,84 [−0,65, +4,59] → +4,06 [+1,14, +6,77] | −0,73 [−4,44, +3,21] → +0,18 [−3,70, +4,51] |
| UCL ≤4 días | −1,35 [−4,77, +1,22] → +0,73 [−3,43, +4,06] | −4,12 [−7,10, −1,42] → −2,91 [−6,80, +0,58] |

Lectura: la caída de 6 a 9 puntos tras las eliminatorias ya no se sostiene como patrón en las dos temporadas; queda entre −5 y −7 puntos con IC que solo excluyen 0 en 2025-26. En 2024-25 la fase de liga muestra incluso una subida significativa (+4,06) con el control corregido. Etiquetas: **descriptivo y exploratorio**; la muestra sigue siendo de 7 y 9 equipos-temporada.
