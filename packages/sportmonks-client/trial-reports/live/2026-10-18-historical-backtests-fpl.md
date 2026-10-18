# Backtests históricos con datos solo de FPL (siete temporadas)

Encargo del revisor, aprobado por Leo el 2026-10-18. Solo análisis con el almacén propio de FPL (`fpl-historical`, temporadas 2019-20 a 2025-26). Cero llamadas a Sportmonks, sin modelo de lenguaje. El plan se escribió y se subió **antes** de mirar ningún resultado: es el primer commit de este PR (`2026-10-18-historical-backtests-fpl-PLAN.md`). Los scripts están en `packages/football-intelligence/scripts/historical_backtests/`.

Escrito para: Leo y el revisor.

## Resultado en una página

| Prueba | Resultado |
|---|---|
| **T1** Titularidad y minutos | **El resultado de F se sostiene con siete temporadas.** M1 predice mejor quién es titular (Brier −0,0145, IC [−0,0155, −0,0133]); la regla simple de FPL predice mejor los minutos (MAE 23,2 contra 26,9). Se cumple en las 7 de 7 temporadas y en los tres tramos de la temporada. |
| **T2** Congestión solo de liga | Con descanso de 3 días o menos entre partidos de liga, los titulares habituales repiten un **1,6 puntos porcentuales menos** que con 6 o más, dentro del mismo equipo (IC [−2,75, −0,50]). Por el umbral preinscrito es "sin efecto relevante". El efecto está en 2019-20 a 2021-22 y desaparece en las cuatro últimas. |
| **T3** Ausencia y reemplazo, línea base FPL | Tras caer un habitual, un recién llegado al once repite en el siguiente partido un **60 %** de las veces, en los dos siguientes un 43 % y en los tres un 33 %. "Barato" no aporta nada. Esta es la barra que debe superar la versión con huecos de Sportmonks. |

## Datos y límites

- **`starts` solo existe en 2025-26.** En las seis temporadas anteriores la titularidad se infiere con `minutos >= 60`. Error medido en 2025-26: exactitud 97,9 % sobre todas las filas (94,5 % entre quienes juegan), 42 falsos titulares y 581 falsos suplentes (titulares sustituidos antes del minuto 60). Con `minutos >= 46`: 98,6 %. Todo lo que dependa de la titularidad antes de 2025-26 lleva ese ruido.
- **xG y xA** solo desde 2022-23 (vacíos en 2019-20 a 2021-22). T1 a T3 no los usan.
- **Reconstrucción de filas.** Las temporadas antiguas no traen fixture, rival, hora ni propiedad por fila. El equipo sale de `players.team_id`, la fila se asigna al fixture de ese equipo en esa jornada (en jornadas dobles, por orden de aparición, comprobando `was_home`). Se descartan las filas cuyo lado local o visitante no cuadra (fichajes a mitad de temporada) o cuyo número no coincide con los fixtures del equipo: 0,4 % a 0,9 % por temporada (2019-20: 74 por lado y 118 por recuento, por la reanudación COVID). En 2025-26 se descartan 409 filas sin fixture asociado.
- **Sin fugas.** No se usa ningún agregado de fin de temporada (`now_cost`, `selected_by_percent` de la tabla de jugadores). La propiedad por jornada solo existe en 2025-26 y no se guarda el total de managers, así que no se usa propiedad; el precio por jornada (`value`) sí. El equipo del jugador sale de la tabla de jugadores (equipo de fin de temporada): no es un resultado, y las filas incoherentes se descartan.
- **2019-20** tiene jornadas 39 a 47 (reanudación COVID, 5 cambios, calendario comprimido). Se excluyen del agregado primario de T2 y se incluyen en la sensibilidad.
- **Desviaciones respecto al plan.** (1) Descarto filas sin equipo o sin hora en 2025-26 (409), una corrección de código para que corra, no de resultados. (2) En T3 añado dos análisis que el plan no preinscribía y que son exploratorios: el subconjunto "el habitual sigue fuera en m+1" (solo se sabe después, no sirve para anticipar) y una referencia sin habitual caído. El resto sigue el plan.

## T1. Regla simple de FPL contra M1 con historial FPL

**Diseño.** 244 puntos de corte elegibles (jornada 4 o posterior, siete temporadas). 200 sorteados sin reemplazo con semilla 20261018: son el resultado primario; los 244 son la sensibilidad. La historia es estrictamente anterior a la jornada de corte; el resultado es lo que pasa en esa jornada. Lista de jugadores fijada antes del corte: al menos una titularidad en sus hasta 6 partidos previos. Predictores, sin ajustar ningún coeficiente: (1) regla simple: titularidades de los últimos 3 partidos entre 3, y minutos = media de los últimos 3; (2) M1 con historial FPL: el módulo `expected_minutes` tal cual, con titularidades y minutos de los últimos 6 partidos (pesos 1 a 6), cameos, y congestión a 21 días con los partidos de liga. IC: bootstrap por conglomerados de partido de equipo (4.022 conglomerados), 2.000 remuestreos.

**Resultado primario (200 puntos, 66.224 filas).**

| | Brier (titular) | MAE minutos |
|---|---|---|
| Tasa base y media | 0,2407 | 37,0 |
| Regla simple | 0,1959 | **23,2** |
| M1 con historial FPL | **0,1814** | 26,9 |
| M1 menos simple | −0,0145 [−0,0155, −0,0133] | +3,65 [+3,55, +3,76] |

Con los 244 puntos (80.444 filas) el resultado es idéntico (−0,0144 y +3,65).

**Por temporada (200 puntos), diferencia M1 menos regla simple.**

| Temporada | Filas | Brier | MAE minutos |
|---|---|---|---|
| 2019-20 | 9.419 | −0,0136 [−0,0166, −0,0107] | +4,09 [+3,80, +4,37] |
| 2020-21 | 9.903 | −0,0137 [−0,0168, −0,0107] | +4,04 [+3,75, +4,32] |
| 2021-22 | 8.770 | −0,0173 [−0,0205, −0,0144] | +3,44 [+3,15, +3,74] |
| 2022-23 | 10.252 | −0,0156 [−0,0186, −0,0128] | +3,49 [+3,24, +3,75] |
| 2023-24 | 8.853 | −0,0121 [−0,0150, −0,0092] | +3,76 [+3,49, +4,04] |
| 2024-25 | 9.349 | −0,0164 [−0,0198, −0,0134] | +3,09 [+2,84, +3,34] |
| 2025-26 | 9.678 | −0,0126 [−0,0157, −0,0097] | +3,63 [+3,36, +3,89] |

**Por tramo de la temporada.** Jornadas 4 a 10: Brier −0,0140 y MAE +3,07 (11.442 filas). Jornadas 11 a 25: −0,0137 y +4,00 (28.464). Jornadas 26 en adelante: −0,0155 y +3,52 (26.318).

**Victoria preinscrita.** M1 gana en titularidad (diferencia negativa, IC que excluye 0, en al menos 5 de 7 temporadas): **sí, en 7 de 7**. La regla simple gana en minutos (diferencia positiva, IC que excluye 0, en al menos 5 de 7): **sí, en 7 de 7**. El resultado de F se sostiene.

**Sensibilidad al proxy.** En 2025-26 con la titularidad inferida (minutos >= 60) como objetivo, la ventaja de M1 en titularidad sube a −0,0203 [−0,0234, −0,0172]: el proxy la exagera algo. Con el `starts` real es −0,0126.

## T2. Congestión solo de liga

**Diseño.** Titulares habituales fijados antes del partido (al menos el 75 % de titularidades en sus hasta 4 partidos previos, mínimo 3). Exposición: días completos de descanso desde el partido de liga anterior del equipo; corto = 3 o menos, largo = 6 o más (se descartan 4 y 5). Resultado: el habitual vuelve a ser titular. Cada equipo contra sí mismo: diferencia corto menos largo por equipo-temporada con ambos grupos, resumen ponderado por el n del grupo corto, IC por bootstrap de conglomerados de equipo-temporada. **FPL solo conoce los partidos de liga: no ve Europa ni copas.** La versión con Europa espera datos de Sportmonks de temporadas pasadas.

**Resultado primario (sin las jornadas COVID de 2019-20).** 140 equipo-temporadas; 891 partidos de descanso corto y 3.034 de largo; 8.026 y 27.232 partidos-jugador habitual. Tasa de titularidad de los habituales: 0,777 con descanso corto y 0,793 con largo. **Diferencia dentro del mismo equipo: −1,59 puntos [−2,75, −0,50].** Con las jornadas COVID: −1,77 [−2,87, −0,72]. Sin emparejar: 0,777 contra 0,794.

**Con los umbrales preinscritos.** "Caída" exigía una media menor que cero con IC que excluya 0 y de al menos 5 puntos: no se cumple. "Sin efecto relevante" exigía el IC entero dentro de ±3 puntos: se cumple ([−2,75, −0,50]). Veredicto: **hay una caída detectable pero pequeña, por debajo del umbral de relevancia.**

| Temporada | Corto menos largo (IC 95 %) | Partidos corto / largo |
|---|---|---|
| 2019-20 (sin jornadas COVID) | −5,2 pp [−8,7, −1,8] | 77 / 355 |
| 2020-21 | −1,7 pp [−4,1, +0,7] | 187 / 368 |
| 2021-22 | −3,4 pp [−6,4, −0,7] | 142 / 442 |
| 2022-23 | −0,1 pp [−2,8, +2,7] | 153 / 424 |
| 2023-24 | −0,6 pp [−3,3, +2,2] | 135 / 465 |
| 2024-25 | −0,9 pp [−3,7, +1,7] | 98 / 494 |
| 2025-26 | −0,3 pp [−3,1, +2,5] | 99 / 486 |

El efecto aparece en las tres primeras temporadas (calendarios más cargados y tres cambios) y no en las cuatro últimas (cinco cambios). Es una descripción; no se prueba que esa sea la causa.

Por descanso exacto, tasa de titularidad de los habituales (n partidos-jugador): 2 días 0,777 (2.838); 3 días 0,779 (5.140); 4 días 0,798; 5 días 0,794; 6 días 0,793; 7 días 0,802; de 8 en adelante entre 0,78 y 0,80.

**Qué implica.** El descanso corto entre partidos de liga cuesta del orden de 1 a 2 puntos de habituales; no sostiene un aviso de rotación fuerte. Falta lo que importa para el aviso del calendario (después de Europa o copa), que FPL no ve.

## T3. Ausencia y reemplazo, línea base solo FPL

**Definición (preinscrita).** Un titular habitual (al menos 3 de sus 4 partidos previos y titular en el anterior) no es titular en el partido m. Candidatos: compañeros del mismo equipo titulares en m con como mucho una titularidad en los 3 partidos previos. Regla solo FPL: además barato (precio por jornada de 5,5 millones o menos), el proxy de baja propiedad. Resultado: `mantiene_k` = titular en cada uno de los siguientes k partidos (k = 1, 2, 3). Referencia (no preinscrita): el mismo tipo de titular en partidos en que no cayó ningún habitual.

**Eventos por temporada** (partidos de equipo con un habitual que cae; filas de candidato): 2019-20 295 (1.268); 2020-21 312 (1.320); 2021-22 301 (1.366); 2022-23 294 (1.176); 2023-24 308 (1.205); 2024-25 299 (1.221); 2025-26 291 (1.240).

**Tasa base: todos los candidatos tras la caída** (mantiene 1 / 2 / 3 partidos):

| Temporada | 1 | 2 | 3 | Baratos (1 / 2 / 3) |
|---|---|---|---|---|
| 2019-20 | 0,621 | 0,452 | 0,350 | 0,625 / 0,459 / 0,357 |
| 2020-21 | 0,586 | 0,413 | 0,316 | 0,583 / 0,421 / 0,328 |
| 2021-22 | 0,605 | 0,416 | 0,314 | 0,586 / 0,396 / 0,305 |
| 2022-23 | 0,593 | 0,400 | 0,291 | 0,590 / 0,399 / 0,298 |
| 2023-24 | 0,605 | 0,447 | 0,348 | 0,593 / 0,438 / 0,339 |
| 2024-25 | 0,577 | 0,395 | 0,305 | 0,576 / 0,386 / 0,298 |
| 2025-26 | 0,634 | 0,457 | 0,364 | 0,623 / 0,456 / 0,370 |

El n por celda va de unos 830 a 1.370 filas (para 3 partidos baja algo porque exige que existan).

**Agrupado, con IC por conglomerados (partido de equipo).**

| Grupo | 1 partido | 2 partidos | 3 partidos | n (1 partido) |
|---|---|---|---|---|
| Todos tras la caída | 0,603 [0,592, 0,615] | 0,426 [0,415, 0,437] | 0,327 [0,316, 0,338] | 8.779 |
| Baratos tras la caída | 0,596 [0,583, 0,610] | 0,422 [0,408, 0,435] | 0,328 [0,315, 0,340] | 6.488 |
| Todos, el habitual sigue fuera en m+1 (solo se sabe después) | 0,731 [0,716, 0,746] | 0,527 [0,509, 0,545] | 0,416 [0,399, 0,433] | 3.397 |
| Baratos, el habitual sigue fuera | 0,733 [0,715, 0,752] | 0,532 [0,510, 0,552] | 0,424 [0,403, 0,445] | 2.545 |
| Referencia: ningún habitual cayó | 0,683 [0,662, 0,705] | 0,517 [0,494, 0,540] | 0,389 [0,366, 0,412] | 2.033 |
| Referencia, baratos | 0,683 [0,658, 0,708] | 0,530 [0,504, 0,556] | 0,400 [0,373, 0,427] | 1.496 |

**Lectura.** Línea base FPL: tras caer un titular, cerca del 60 % de los recién llegados repite en el partido siguiente, el 43 % en los dos siguientes y el 33 % en los tres. "Barato" no aporta nada sobre "cualquiera". Un recién llegado dura casi igual con o sin hueco abierto; la caída del habitual solo sube la continuidad inmediata (de 0,60 a 0,73) cuando el habitual sigue fuera, y eso solo se sabe después. Antes de 2025-26 el proxy de titularidad (minutos >= 60) cuenta como "no titular" a los suplentes tempranos, lo que puede bajar algo las tasas; en 2025-26, con `starts` real, son las más altas (0,634 / 0,457 / 0,364). Es la barra que tendrá que superar la versión con huecos de Sportmonks.

## Qué no se pudo hacer y qué sigue

- La versión de T2 con Europa y copas espera los datos de Sportmonks de temporadas pasadas (paso 1, a cargo de otro constructor).
- No hay titularidad real antes de 2025-26: todo el ruido del proxy está en seis de las siete temporadas.
- No hay propiedad histórica por jornada, por lo que la regla de "baja propiedad" de T3 es un proxy de precio.
- La reconstrucción del equipo de cada jugador usa el equipo de fin de temporada; las filas incoherentes (fichajes) se descartan, pero un fichaje entre equipos con el mismo lado en una jornada pasaría sin detectar.
