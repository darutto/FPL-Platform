# Backtests con Sportmonks de temporadas pasadas: plan preinscrito (18 oct 2026)

Este fichero se escribe y se sube **antes de mirar ningún dato nuevo** (las capturas de Sportmonks de 2024-25 y 2025-26 y de los partidos europeos y de copa de los clubes ingleses). Lo que ya se conoce y no cuenta como "dato nuevo": el almacén de 2026-27 hasta hoy, los resultados de #472, #475 y #478 y la estructura del feed (la posición detallada es función de formación, casilla y lugar del partido). Cualquier desviación se anota en el informe final como desviación, con su commit.

Encargo: revisor fpl-platform-22, bajo el visto bueno permanente de Leo (solo análisis, cero llamadas a Sportmonks; la captura la hace el constructor de add-ons). Sin LLM. Sin datos crudos ni identificadores del proveedor en git: los scripts leen de `trial-output` local y solo se publican agregados.

## Reparto de temporadas

- **Desarrollo: 2024-25.** Aquí se pueden mirar los datos para comprobar que las definiciones funcionan (formato, cobertura, mapeos). **No se ajusta ningún umbral para mejorar un resultado.** Cualquier cambio de definición tras ver 2024-25 se registra como enmienda, con commit anterior a mirar 2025-26.
- **Confirmación: 2025-26.** Los criterios de aprobado se evalúan aquí. Se mira una vez, con las definiciones congeladas.
- **Tercera comprobación: 2026-27 hasta hoy** (almacén local GW1 a GW6 más el sábado de GW7 y lo que haya después), solo informativa por su tamaño.

## Estados de participación (i156), en todas partes

Para cada jugador y partido de liga de su equipo:
- **titular**: en el once inicial.
- **not_started**: no titular, pero juega minutos (entra desde el banquillo).
- **did_not_play**: no juega ningún minuto y no hay baja registrada.
- **unavailable**: hay una fila de baja de Sportmonks (lesión o sanción) que cubre la fecha del partido.
Una lesión previa no implica que estuviera descartado en el partido. **Las bajas de Sportmonks que tengo son las de hoy, no las de aquel día**: todo lo que use `unavailable` queda como **retrospectivo** y se dice. "Salir del once" cuenta los tres estados.

## Datos, identidad y reglas comunes

- **Posición cruda por titularidad de liga** = `detailedPosition` + `formation_field` (casilla de la rejilla) + formación del equipo + local o visitante. El rol y la banda se obtienen con `role-map-v3` (estimación nuestra); lo crudo y lo estimado se mantienen separados.
- **Identidad.** Jugador y equipo del proveedor se unen con FPL (para los comparadores de FPL) por nombre y fecha de nacimiento, con el mapeo que entregue la captura. Se informa la tasa de emparejamiento; los jugadores sin pareja se excluyen y se cuentan. Los análisis de H1 a H3 no necesitan FPL salvo los comparadores indicados.
- **Club en la fecha (G).** Se aplica la comprobación contra una fuente independiente (el fixture de FPL cuando el jugador tiene pareja; el equipo de la alineación del proveedor cuando no). Se excluyen los **fichajes recién llegados**: un jugador cuyo primer partido de liga con ese club cae entre los 4 partidos previos al evento.
- **Listas fijadas antes del partido.** Titular habitual = al menos 3 de sus últimos 4 partidos de liga como titular (mínimo 3 previos). Toda lista y todo predictor usan solo partidos anteriores al partido evaluado.
- **Regla de tiempo (I).** La captura no trae marca de tiempo por alineación; salvo las filas del vigilante de 2026-27, todo lo que dependa de alineaciones se etiqueta **retrospectivo**.
- **IC.** Bootstrap por conglomerados (partido de equipo; en H3, equipo-temporada), 2.000 remuestreos, semilla fija 20261018.
- **Calendario europeo y de copa**: los partidos de UCL, UEL, UECL, Supercopa, FA Cup y EFL Cup de los clubes ingleses entran como calendario con su hora; en ellos puede no haber alineaciones.

## H1. Detector de cambios de rol

- **Unidad:** serie de titularidades de liga de un jugador en una temporada.
- **Rol base** R0 = rol modal de sus 3 o más titularidades anteriores a la racha nueva. **Rol nuevo** R1 distinto de R0 (rol o banda).
- **Alerta "posible":** las 1 o 2 últimas titularidades consecutivas están en R1 distinto de R0. **Alerta "confirmado":** las 3 últimas consecutivas están en R1.
- **Cambio individual contra de equipo:** se separa. Es de **equipo** si la formación del equipo en la titularidad de arranque difiere de la formación del partido anterior; es **individual** si la formación es la misma y cambia el rol del jugador. Se informan por separado y la métrica principal usa solo los individuales.
- **Persistencia (precisión):** el nuevo rol persiste si en al menos 2 de las 3 titularidades siguientes (hay que tener 3 siguientes) el jugador está en R1; estricta: en las 3. Se informa por nivel de alerta.
- **Línea base** "mismo rol que la última titularidad": se evalúa como predictor del rol de la siguiente titularidad, junto al detector, que predice R1 con "confirmado" y R0 con "posible". Se compara la exactitud de los dos en los casos "posible" y "confirmado".
- **Adelanto frente a la señal visible en FPL.** Señal FPL = el xGI/90 de sus últimos 3 partidos supera en al menos 0,15 al de los 6 anteriores (con al menos 150 minutos en cada ventana), medido tras cada partido, usando FPL de la temporada correspondiente (xG existe desde 2022-23). Adelanto = número de partidos de liga entre la alerta "posible" y el primer partido en que la señal FPL es cierta (positivo = Sportmonks antes), restringido a eventos con señal FPL en los 6 partidos siguientes a la alerta. Se informan la mediana del adelanto, la proporción de alertas que preceden, coinciden o siguen a la señal FPL, y como control la frecuencia de la señal FPL en jugadores sin cambio de rol. Solo asociación.
- **Aprobado (confirmación 2025-26):** la persistencia de "confirmado" (individual, al menos 2 de 3) es **al menos 0,75 con el límite inferior del IC en al menos 0,70**, y es mayor que la persistencia de "posible" con el IC de la diferencia excluyendo 0; y el detector no es peor que la línea base en exactitud de rol siguiente en los casos "confirmado". Sin criterio duro para el adelanto (descriptivo).

## H2. Relevo por hueco frente a la línea base FPL de #478 T3 (60 / 43 / 33 %)

- **Evento:** un titular habitual que titulaba el partido anterior deja de ser titular en el partido m (cuenta not_started, did_not_play y unavailable). Para cada ausente se fija su hueco modal en sus 3 últimas titularidades y su formación en la última.
- **Candidato de hueco:** el jugador que es titular en m en el **mismo hueco** (rol y banda) y con la **misma formación** del equipo que la del ausente (un hueco igual en otra formación no cuenta como relevo real). Se excluyen fichajes recién llegados (G).
- **Dos poblaciones:** (a) todos los candidatos de hueco; (b) solo los que tenían como mucho una titularidad en los 3 partidos previos, que es la población comparable con T3.
- **Resultado:** `mantiene_k` = titular en cada uno de los siguientes k partidos de liga (k = 1, 2, 3), y como medida adicional "mantiene el mismo hueco".
- **Comparadores:** (1) las tasas de #478 T3 (agrupadas 0,603 [0,592, 0,615], 0,426 [0,415, 0,437], 0,327 [0,316, 0,338]; por temporada 2024-25: 0,577 / 0,395 / 0,305; 2025-26: 0,634 / 0,457 / 0,364); (2) la regla FPL aplicada sobre las mismas alineaciones de Sportmonks: candidatos que son titulares en m con como mucho una titularidad en los 3 previos y que **no** ocupan el hueco del ausente.
- **Subgrupo:** el ausente tiene fila de baja de Sportmonks que cubre el partido (estado unavailable) frente a no. Todo retrospectivo (bajas de hoy).
- **Aprobado (confirmación 2025-26):** el relevo por hueco (población b) supera la línea base FPL con los IC **sin solaparse**: el límite inferior del IC del relevo por hueco es mayor que el límite superior del IC de la tasa FPL de T3 en k = 1, 2 y 3, y la diferencia emparejada con el comparador (2) tiene IC que excluye 0 en k = 1 y k = 2. Si solo se cumple en parte, se informa como parcial.

## H3. Rotación tras partidos europeos

- **Habituales** fijados antes del partido (definición común).
- **Exposición:** partido de liga en que el partido anterior del club, de cualquier competición, fue de UCL, UEL o UECL con hasta 3 días de descanso (definición principal) o hasta 4 días (secundaria). **Control:** partidos de liga del mismo equipo cuyo partido anterior fue de liga con 5 o más días de descanso.
- **Resultado:** el habitual es titular. Cada equipo contra sí mismo: diferencia de tasa exposición menos control por equipo-temporada con ambos grupos (al menos 1 partido en cada uno), resumen ponderado por el n de exposición, IC por bootstrap de equipo-temporada. Se informan 2024-25, 2025-26 y 2026-27 hasta hoy por separado.
- **Aprobado (confirmación 2025-26), mismos umbrales que #478 T2:** "caída" = media menor que cero con IC que excluye 0 y de al menos 5 puntos porcentuales; "sin efecto relevante" = IC entero dentro de ±3 puntos; en otro caso "no concluyente".
- **Exploratorio (etiquetado como tal, no entra en el aprobado):** partidos europeos de alto riesgo frente al resto. Alto riesgo = eliminatoria de la fase final (octavos o posterior, repesca, final); la presencia de un rival de élite no se puede definir sin una lista de clubes que no está en la captura, así que no se intenta salvo que la captura traiga clasificación. Es la hipótesis de Leo (partidos tipo PSG) tratada como pregunta abierta; con n pequeño se informa sin conclusión.

## H4. M1 con entradas de Sportmonks, M1 con entradas de FPL y regla simple

- **Puntos de corte:** todas las jornadas de liga 4 o posteriores de cada temporada (sin muestreo), historia estrictamente anterior a la jornada.
- **Lista:** jugadores con al menos 1 titularidad de Sportmonks en sus hasta 6 partidos previos de liga y fila en la jornada evaluada.
- **Objetivo:** titular y minutos reales de la alineación de Sportmonks (el mismo para los tres predictores).
- **Predictores, sin ajustar coeficientes:** (1) regla simple: titularidades de los últimos 3 partidos entre 3, minutos = media de los últimos 3 (sobre la serie de FPL, mapeada); (2) M1 con entradas de FPL: titularidades y minutos de FPL de los últimos 6 partidos (con el proxy de minutos 60 o más donde FPL no tiene `starts`) y congestión solo con partidos de liga; (3) M1 con entradas de Sportmonks: titularidades y minutos de la alineación de Sportmonks de los últimos 6 partidos de liga y congestión a 21 días con liga, copas nacionales (peso 1,0) y europeas (peso 1,25), con el calendario conocido de antemano.
- **Métricas:** Brier de titular y MAE de minutos, con y sin las filas en estado unavailable (retrospectivo).
- **Aprobado (confirmación 2025-26):** (3) mejor que (2) en Brier con IC de la diferencia que excluye 0 (a favor de Sportmonks); lo mismo para el MAE de minutos. Contra la regla simple se informa en las dos métricas sin criterio duro (en #478 M1 ganaba en titularidad y perdía en minutos).

## Qué se entrega

Un informe en español `2026-10-18-historical-backtests-sportmonks.md` (la fecha de creación; si se entrega otro día se usará la fecha de entrega) y scripts bajo `packages/football-intelligence/scripts/historical_backtests/`. Borrador de PR, sin mergear. Resultados por prueba según se terminen. Plazo: antes del jueves 22 para la decisión del 23 de octubre.
