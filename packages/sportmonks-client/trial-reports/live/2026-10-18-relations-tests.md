# Pruebas de relaciones entre jugadores: anticipación, explicación, auditoría, rotación y M1 (18 oct 2026)

Encargo aprobado por Leo el 2026-10-18, a partir de la conclusión de la lectura de Q1 a Q8 (#472): el valor de Sportmonks está en las relaciones entre jugadores (quién ocupa qué hueco, cambios de rol), no en predecir minutos. Este informe lo pone a prueba con datos ya capturados. Cero llamadas nuevas a Sportmonks. La API pública de FPL (`bootstrap`, `fixtures`, `element-summary`) sí se consultó. Una sola parte usa un modelo de lenguaje (L, openai/gpt-5.6-luna), y solo para redactar sobre hechos construidos por script.

Escrito para: Leo y el revisor.

## Resultado en una página

| Prueba | Pregunta | Resultado |
|---|---|---|
| J | ¿Se podía anticipar a los sustitutos directos? | **No.** Solo se explican a posteriori. En 18 de 21 pares el relevo ocurre en el mismo partido en que el titular deja de serlo; una regla solo de FPL acierta tanto (o más) que la relación de hueco al predecir quién sigue de titular. |
| L | ¿Una explicación con hechos de Sportmonks es mejor que una solo con FPL? | **Aporta información nueva en 5 de 5** (posición real, rol, formación, relación con ausentes). Los números de ambas versiones se verifican. Utilidad: la puntúa Leo. |
| A | Auditoría partido a partido de Miley, Iwobi y Kamada | Los cambios empiezan en GW5 (Miley), GW4 (Iwobi) y GW3 (Kamada), y se mantienen. Mi ventana de Q2 detectaba tarde. La comprobación inversa de Miley no se puede hacer: Dedić no ha vuelto al once. |
| G | ¿Cada jugador está en el club correcto en la fecha? | **0 desacuerdos** en 1.951 partidos de jugador. 5 jugadores cambian de club en la muestra; 2 corregían Q8. |
| B | ¿Rota cada equipo más tras Europa o copa que consigo mismo? | **No se ve** (n pequeño). El parón de selecciones cuesta más que cualquier partido europeo. |
| F | M1 en tres versiones | M1 acierta más **quién es titular** que la regla simple (Brier −0,012), pero la regla simple gana en **minutos** (MAE 19,1 contra 21,6 y 22,7). Sportmonks no añade nada fiable sobre M1 con FPL. |
| D | Aviso de rotación en #464 | Copy descriptivo en el PR #474, sin tocar la lógica. |

En una frase: **Sportmonks explica bien (quién ocupa el hueco de quién, desde cuándo), pero estos datos no demuestran que anticipe ni que prediga mejor que FPL solo.** Lo que se puede defender hoy es la explicación, no la predicción.

## Reglas comunes

- **Regla de tiempo (I).** En cada hallazgo se anota cuándo ocurrió el evento y si el dato que lo muestra estaba disponible antes de la fecha límite de la siguiente jornada. La captura no trae marca de tiempo por alineación; solo las filas del vigilante de GW6-último y de GW7 la tienen, y el registro de bajas (sidelined) arranca el 11 oct. Por eso todo lo que dependa de las alineaciones queda estrictamente como **retrospectivo**. Como sensibilidad, supongo que el proveedor publica la alineación al acabar el partido (inicio más 2 horas), sin demostrarlo.
- **Datos.** Alineaciones de liga de Sportmonks GW1 a GW6 (almacén local construido el 13 oct) más el sábado de GW7 (once y rejilla del vigilante); minutos, titularidades y xG de FPL. Copas y Europa: solo calendario. Los partidos europeos del 13 al 15 oct se cuentan como jugados por su hora.
- **Hecho crudo contra estimación.** Hecho crudo: formación, casilla, posición detallada, minutos. Estimación nuestra: `role-map-v3` y M1 (coeficientes a mano).
- **Nombres.** Verificados contra el bootstrap actual de FPL. Sin identificadores del proveedor ni cargas crudas en git. Los scripts están en `packages/football-intelligence/scripts/relations_tests/`.

## J. Anticipación de los sustitutos directos de Q8

**Qué se probó.** Para cada pareja titular que sale del once y compañero que ocupa exactamente su hueco: ¿se podía marcar al sustituto como probable titular con los datos anteriores a la fecha límite de la jornada de su primer relevo? ¿Conservó el hueco? Se compara con una regla solo de FPL (propiedad baja y titularidades al alza). La comprobación G eliminó dos pares: Ndiaye (MCI, por Foden) y Grealish (EVE, por George) son fichajes recién llegados, no sustitutos; además George → Grealish cambia de formación (4-1-4-1 contra 4-2-3-1), que no cuenta como reemplazo real. Quedan **21 pares**, todos en la misma formación.

**Cuándo.** En **18 de 21** el sustituto ocupa el hueco en el mismo partido en que el titular deja de serlo: ninguna alineación previa puede anticiparlo, así que el primer relevo siempre es retrospectivo. Solo **3** tenían la ausencia ya visible antes de la fecha límite de la jornada del relevo (Henderson CHE por James y por Lavia; Maitland-Niles EVE por Röhl); incluso ahí el dato dice que el hueco está libre, no quién lo ocupa.

**¿Conservó el hueco?** Tras el primer relevo, fue titular en todos los partidos siguientes en **18 de 21**, y en exactamente el mismo hueco todas las veces en **15 de 21** (de 1 a 5 partidos después).

**Causa de la ausencia (21 pares).** Lesión o sanción registrada que cubre la fecha de la ausencia: 1 (Kluivert, BOU, por Christie). Decisión técnica (el ausente entra de suplente en algún partido que no empieza): 11. Registro posterior a la ausencia, que no la explica: 1. Sin registro: 8. En Q8 llamé "lesión confirmada" a más casos; Gakpo, James y Lavia tienen un registro que empieza después de su primera ausencia. Ni siquiera el caso de Kluivert se podía haber visto antes: el registro de bajas arranca el 11 oct.

**Contra la regla solo de FPL, en toda la liga.** Muestra: 96 jugadores que acaban de entrar al once (titulares en el partido anterior con una titularidad o menos en los 3 previos), sin fichajes.
- Regla FPL (propiedad inferior al 5 % y titularidades al alza): titulares en el siguiente partido 67 de 94 (71 %).
- Sportmonks, "explicado" (ocupa el hueco de un habitual ausente, misma formación): 44 de 66 (67 %).
- Sportmonks, "no explicado": 25 de 30 (83 %).

La relación de hueco **no mejora la predicción**: los relevos directos duran algo menos que los que llegan sin hueco claro, probablemente porque son temporales mientras el titular vuelve. Las dos señales aparecen después del primer partido del sustituto. Sportmonks explica mejor ("sustituye a X desde tal fecha"), pero no marca antes ni acierta más. Conclusión: **explicación sí, anticipación no demostrada**.

#### Los 21 pares
| Ausente | Sustituto | Club | Hueco | Primera ausencia | Primer relevo | GW | Partidos desde el relevo, el primero incluido (titular/total) | Mismo hueco | Causa | Prop. % |
|---|---|---|---|---|---|---|---|---|---|---|
| Pau | Mings | AVL | center_back/center | 05-Sep | 05-Sep | 3 | 4/5 | 4/5 | decision tecnica (entra de suplente) | 0.3 |
| Barkley | Gomes | AVL | central_midfield/center | 19-Sep | 19-Sep | 5 | 3/3 | 3/3 | decision tecnica (entra de suplente) | 0.0 |
| Kluivert | Christie | BOU | attacking_midfield/center | 20-Sep | 20-Sep | 5 | 2/2 | 1/2 | lesion/sancion registrada | 0.0 |
| Collins | Schuster | BRE | center_back/center | 12-Sep | 12-Sep | 4 | 3/4 | 3/4 | desconocida | 0.1 |
| M.Sangaré | Yarmoliuk | BRE | central_midfield/center | 18-Sep | 18-Sep | 5 | 3/3 | 3/3 | decision tecnica (entra de suplente) | 0.6 |
| Dunk | Struijk | BHA | center_back/center | 19-Sep | 19-Sep | 5 | 2/2 | 2/2 | decision tecnica (entra de suplente) | 0.2 |
| James | Henderson | CHE | central_midfield/center | 18-Sep | 17-Oct | 7 | 1/1 | 1/1 | desconocida (registro posterior) | 0.8 |
| Gusto | Neto | CHE | winger/right | 06-Sep | 06-Sep | 3 | 5/5 | 5/5 | decision tecnica (entra de suplente) | 1.2 |
| Fofana | Acheampong | CHE | center_back/center | 10-Oct | 10-Oct | 6 | 2/2 | 1/2 | desconocida | 0.3 |
| Lavia | Henderson | CHE | central_midfield/center | 18-Sep | 17-Oct | 7 | 1/1 | 1/1 | decision tecnica (entra de suplente) | 0.8 |
| Henderson | Benitez | CRY | goalkeeper/center | 12-Sep | 12-Sep | 4 | 3/3 | 3/3 | desconocida | 0.1 |
| Röhl | Maitland-Niles | EVE | full_back/right | 12-Sep | 19-Sep | 5 | 3/3 | 3/3 | desconocida | 1.0 |
| Stroud | Thomas | HUL | winger/left | 19-Sep | 19-Sep | 5 | 3/3 | 3/3 | decision tecnica (entra de suplente) | 0.0 |
| Fatawu | Maeda | IPS | winger/right | 10-Oct | 10-Oct | 6 | 2/2 | 1/2 | decision tecnica (entra de suplente) | 0.2 |
| Scherpen | Walton | IPS | goalkeeper/center | 19-Sep | 19-Sep | 5 | 3/3 | 3/3 | desconocida | 0.4 |
| Gakpo | Barcola | LIV | winger/left | 12-Sep | 12-Sep | 4 | 4/4 | 4/4 | decision tecnica (entra de suplente) | 2.1 |
| Gvardiol | O'Reilly | MCI | full_back/left | 11-Oct | 11-Oct | 6 | 2/2 | 2/2 | decision tecnica (entra de suplente) | 9.5 |
| Khusanov | Matheus N. | MCI | full_back/right | 13-Sep | 13-Sep | 4 | 4/4 | 4/4 | decision tecnica (entra de suplente) | 0.9 |
| Elanga | J.Murphy | NEW | winger/right | 14-Sep | 14-Sep | 4 | 3/4 | 3/4 | desconocida | 0.1 |
| Milenković | Diomande | NFO | center_back/center | 12-Sep | 12-Sep | 4 | 3/3 | 3/3 | desconocida | 0.5 |
| Jair Cunha | Diomande | NFO | center_back/center | 12-Sep | 12-Sep | 4 | 3/3 | 3/3 | desconocida | 0.5 |

## L. Explicación A/B: FPL solo contra FPL más Sportmonks

**Diseño.** Cinco casos: De Cuyper (BHA), Iwobi (FUL), L.Miley (NEW), Barcola (LIV) y Matheus Nunes (MCI). Mismo corte de tiempo en las dos versiones: solo lo público antes de la fecha límite de GW7 (17 oct 10:00 UTC), es decir, GW1 a GW6. Los hechos se construyen con scripts, sin modelo de lenguaje. Versión 1: puntos, minutos, titularidades, xG, xA, precio, propiedad y próximos rivales con su dificultad. Versión 2: lo mismo más formación, posición detallada y rol por partido, cambio de hueco, habituales que no estaban en el once en los partidos en su hueco actual, y calendario de copas y Europa. Mismo prompt y mismo modelo (openai/gpt-5.6-luna, según la respuesta del proveedor), 90 a 120 palabras, solo con los hechos dados. Una llamada de Barcola V2 devolvió texto vacío por el presupuesto de tokens y se repitió con más margen (4.000 tokens de salida) y el mismo prompt.

**Verificación de números.** Se extrajeron todas las cifras de cada texto y se compararon con los hechos que recibió: **0 de 10 textos tienen una cifra que no esté en sus hechos**.

**Lectura.**
- Información nueva: la versión 2 añade posición real, rol y formación en 5 de 5 casos (la versión 1 en 0) y relación con ausentes del once en 5 de 5, sin afirmar causa.
- Verificable: las dos pasan la comprobación numérica; las afirmaciones nuevas de la versión 2 se pueden comprobar en Sofascore (De Cuyper de extremo izquierdo en un 4-2-3-1 los seis partidos; Iwobi de central de centro a extremo izquierdo; Miley de lateral derecho en los dos últimos; Barcola de extremo izquierdo; Matheus N. de lateral derecho).
- Comprensible: entre 107 y 119 palabras cada una; la versión 2 usa "puesto" y "ausencias" y cubre sus afirmaciones con "no se puede confirmar la causa".
- Útil para decidir: la puntúa Leo, con páginas ciegas X/Y y clave (locales, en `trial-output/relations/`).
- Riesgos de la versión 2: la lista de "ausencias" del once no distingue lesión de decisión técnica (en Barcola y Matheus N. salen Szoboszlai, Isak y Foden, que pudieron jugar de suplentes) y tiende a recomendar "vigilar si conserva el puesto".

## A. Auditoría partido a partido: Miley, Iwobi, Kamada

Cada fila es un partido de liga con alineación de Sportmonks y minutos, xG, xA y puntos de FPL; copas y Europa aparecen solo como calendario. Aviso: el partido europeo del 15 oct se cuenta como jugado por su hora.

#### L.Miley

| Fecha | Comp | Rival | Sede | GW | Formación | Casilla exacta | Rol | Min | Tit | xG | xA | Pts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 23-Aug | PL | Liverpool | H | 1 | 4-2-3-1 | Central Midfield | central_midfield/center | 75 | 1 | 0.05 | 0.01 | 3 |
| 26-Aug | EFL | West Bromwich  | H | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 29-Aug | PL | Tottenham Hots | A | 2 | 4-2-3-1 | Central Midfield | central_midfield/center | 90 | 1 | 0.00 | 0.04 | 3 |
| 05-Sep | PL | AFC Bournemout | H | 3 | 4-2-3-1 | Central Midfield | central_midfield/center | 62 | 1 | 0.00 | 0.02 | 2 |
| 08-Sep | EFL | Millwall | A | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 14-Sep | PL | Leeds United | A | 4 | 4-2-3-1 | Central Midfield | central_midfield/center | 79 | 1 | 0.00 | 0.03 | 0 |
| 19-Sep | PL | Hull City | H | 5 | 4-2-3-1 | Right Back | full_back/right | 90 | 1 | 0.00 | 0.04 | 4 |
| 12-Oct | PL | Coventry City | A | 6 | 4-2-3-1 | Right Back | full_back/right | 58 | 1 | 0.00 | 0.01 | 1 |
| 17-Oct | PL | Aston Villa | H | 7 | 4-2-3-1 | Right Back | full_back/right | 90 | 1 | 0.00 | 0.30 | 2 |

#### Iwobi

| Fecha | Comp | Rival | Sede | GW | Formación | Casilla exacta | Rol | Min | Tit | xG | xA | Pts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 24-Aug | PL | Chelsea | H | 1 | 4-2-3-1 | Central Midfield | central_midfield/center | 90 | 1 | 0.00 | 0.04 | 2 |
| 27-Aug | EFL | AFC Wimbledon | H | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 30-Aug | PL | Sunderland | A | 2 | 4-2-3-1 | Central Midfield | central_midfield/center | 90 | 1 | 0.01 | 0.40 | 2 |
| 05-Sep | PL | Crystal Palace | H | 3 | 4-2-3-1 | Central Midfield | central_midfield/center | 82 | 1 | 0.04 | 0.26 | 2 |
| 12-Sep | PL | Liverpool | A | 4 | 4-2-3-1 | Left Midfield | winger/left | 76 | 1 | 0.15 | 0.11 | 3 |
| 15-Sep | EFL | West Ham Unite | A | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 20-Sep | PL | Manchester Uni | H | 5 | 4-2-3-1 | Left Midfield | winger/left | 70 | 1 | 0.19 | 0.41 | 5 |
| 10-Oct | PL | Ipswich Town | A | 6 | 4-2-3-1 | Left Midfield | winger/left | 86 | 1 | 0.00 | 0.19 | 4 |
| 17-Oct | PL | Hull City | H | 7 | 4-2-3-1 | Left Midfield | winger/left | 90 | 1 | 0.28 | 0.93 | 11 |

#### Kamada

| Fecha | Comp | Rival | Sede | GW | Formación | Casilla exacta | Rol | Min | Tit | xG | xA | Pts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 22-Aug | PL | Everton | A | 1 | 3-4-2-1 | Central Midfield | central_midfield/center | 90 | 1 | 0.00 | 0.27 | 3 |
| 28-Aug | PL | Manchester Cit | H | 2 | 3-4-2-1 | Central Midfield | central_midfield/center | 90 | 1 | 0.05 | 0.02 | 2 |
| 05-Sep | PL | Fulham | A | 3 | 3-4-2-1 | Attacking Midfield | attacking_midfield/center | 88 | 1 | 0.00 | 0.01 | 5 |
| 08-Sep | EFL | Middlesbrough | H | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 12-Sep | PL | Ipswich Town | H | 4 | 3-4-2-1 | Attacking Midfield | attacking_midfield/center | 83 | 1 | 0.00 | 0.05 | 8 |
| 17-Sep | UEL | Lech Poznań | H | - | - | sin alineación en la captura | - | - | - | - | - | - |
| 20-Sep | PL | Leeds United | A | 5 | 3-4-2-1 | Attacking Midfield | attacking_midfield/center | 90 | 1 | 0.42 | 0.03 | 3 |
| 11-Oct | PL | Nottingham For | H | 6 | 3-4-2-1 | Attacking Midfield | attacking_midfield/center | 89 | 1 | 0.34 | 0.04 | 8 |
| 15-Oct | UEL | Olympique Lyon | A | - | - | sin alineación en la captura | - | - | - | - | - | - |

**Cuándo empieza cada cambio.**
- **Kamada (CRY, 3-4-2-1):** centrocampista central en GW1 y GW2; mediapunta desde **GW3** (5 sep, Fulham) y cuatro partidos seguidos (GW3 a GW6). Coincide con lo que dice FBref. En Q2 mi ventana de 3 partidos solo lo detectó al cumplirse el tercero: la ventana retrasa dos partidos la detección.
- **Iwobi (FUL, 4-2-3-1):** centrocampista central en GW1 a GW3; extremo izquierdo desde **GW4** (12 sep, Liverpool fuera) y cuatro seguidos (GW4 a GW7). No empezó en GW5 como parecía en Q2.
- **Miley (NEW, 4-2-3-1):** centrocampista central en GW1 a GW4, siempre con Dedić en el once; lateral derecho desde **GW5** (19 sep, Hull) y tres seguidos (GW5, GW6 y el sábado de GW7), siempre con Dedić fuera.

**Resultados por tramo** (n = partidos; minutos; xG, xA):
- Iwobi centrocampista central GW1 a GW3: n=3, 262 min, xG 0,05, xA 0,70, xGI/90 0,26. Extremo izquierdo GW4 a GW7: n=4, 322 min, xG 0,62, xA 1,64, xGI/90 0,63. El sábado contra Hull: xA 0,93 y 11 puntos.
- Kamada centrocampista central GW1 a GW2: n=2, 180 min, xG 0,05, xA 0,29, xGI/90 0,17. Mediapunta GW3 a GW6: n=4, 350 min, xG 0,76, xA 0,13, xGI/90 0,23. Sube la parte de xG y cae la de xA.
- Miley centrocampista central GW1 a GW4: n=4, 306 min, xG 0,05, xA 0,10, xGI/90 0,04. Lateral derecho GW5 a GW7: n=3, 238 min, xG 0,00, xA 0,35, xGI/90 0,13.

**Comprobación inversa de Miley y Dedić.** Dedić (NEW) fue titular en GW1 a GW4 (90, 90, 90 y 57 minutos) y después sumó 0, 31 (suplente, GW6) y 0. En GW6 entró de suplente y Miley siguió de lateral derecho. Dedić todavía no ha vuelto al once, así que la pregunta "¿vuelve Miley al medio cuando Dedić juega?" **no se puede responder con estos datos** (n=0 partidos con Dedić titular tras el cambio; el único caso, Dedić solo de suplente, no revierte). FPL lo muestra "disponible" sin noticia desde GW5.

Cuidado: n de 2 a 4 partidos por tramo, rival y local o visitante sin controlar, y el xG de un solo partido es muy ruidoso.

## G. Club correcto en la fecha de cada partido

**Qué es.** La función `club_on_date_check` compara el club que el análisis asigna al jugador en cada partido con una fuente independiente: el fixture de FPL de ese partido (cada fila de `element-summary` trae el fixture y si el jugador jugó en casa, y los fixtures de FPL dicen qué equipo era local o visitante). `verified_starts()` la aplica y aborta si hay un desacuerdo; J, B y F la usan.

**Resultado.** 1.951 partidos de jugador (429 jugadores, liga GW1 a GW6 más el sábado de GW7): **0 desacuerdos con FPL**. La tabla de plantillas de Sportmonks guarda solo la plantilla actual (una fila por jugador), así que su comprobación de ventanas da 6 falsos avisos en partidos previos al traspaso y no sirve como historial; el club por partido sale de la alineación y se valida con FPL.

**Cambios de club en la muestra (5).** Enzo (CHE a MCI, desde el 5 sep), Muñoz (CRY a NFO, desde el 5 sep), Ndiaye (EVE a MCI, desde el 5 sep), Grealish (MCI a EVE, desde el 6 sep) e Iroegbunam (EVE a HUL, desde el 12 sep). Consecuencias: Ndiaye y Grealish aparecían en Q8 como beneficiarios de salidas ajenas y eran fichajes recién llegados; Q8 queda en 21 de 23 relaciones. En Q1, Muñoz se sumó entre CRY y NFO (1 y 3 titularidades): es el mismo jugador en dos clubes.

## B. Rotación de cada equipo comparada consigo mismo

**Diseño.** Para cada partido de liga de un equipo, la lista de titulares habituales se fija **antes** del partido, solo con los partidos anteriores del equipo: al menos el 75 % de titularidades en sus 2 a 4 partidos previos. Resultado: fracción de esos habituales que vuelve al once. Cubos: después de Europa (Champions, Europa League, Conference o Supercopa entre los dos partidos de liga), después de copa (Carabao), solo liga (sin partido entre medias) y tras el parón de selecciones (más de 12 días). 86 partidos de equipo, con el club verificado por G.

| Cubo | n | Equipos | Habituales por partido | Retención | Habituales que faltan |
|---|---|---|---|---|---|
| Después de Europa | 11 | 8 | 9,0 | 0,85 | 1,36 |
| Después de copa | 18 | 18 | 9,6 | 0,83 | 1,61 |
| Solo liga | 37 | 19 | 9,4 | 0,87 | 1,27 |
| Tras el parón de selecciones | 20 | 20 | 10,3 | 0,79 | 2,10 |

Con la regla estricta (al menos 3 partidos previos, 67 partidos) las conclusiones son las mismas con menos n (solo liga n=18).

**Cada equipo contra sí mismo** (diferencia de retención respecto a sus propios partidos solo liga):
- Después de Europa: 8 equipos, diferencia media −0,05 (unos 0,5 habituales menos por partido); 6 más bajos, 1 más alto, 1 igual; 11 partidos contra 8 de referencia. CRY −0,22, MUN −0,14, MCI −0,09; ARS +0,09. Un partido por equipo en casi todos.
- Después de copa: 17 equipos, −0,05; 9 más bajos, 5 más altos, 3 iguales; 17 partidos contra 31. Mayores bajas: CRY −0,43, AVL −0,34, IPS −0,15; mayores subidas: LEE +0,15, HUL +0,13.

**Lectura.** Tras Europa o copa se pierde del orden de medio titular habitual por partido frente a los partidos solo liga del mismo equipo, pero con 1 a 3 partidos por equipo no se distingue de la variación normal. El efecto grande es el parón de selecciones (retención 0,79).

## F. M1 en tres versiones (evaluación, sin ajustar coeficientes)

**Diseño.** Origen móvil GW2 a GW7 (el sábado en GW7). Para cada partido terminado de liga y cada jugador de la lista fijada **antes** del partido (al menos una titularidad en sus hasta 6 partidos previos), se predice "¿titular?" y "¿cuántos minutos?" y se compara con FPL. n=1.503 filas, 317 jugadores (GW2 216, GW3 253, GW4 273, GW5 290, GW6 308, GW7 163); tasa base de titulares 0,727. Cada predicción usa solo partidos anteriores.
1. Regla simple de FPL: titularidades de los últimos 3 partidos entre 3; minutos = media de los últimos 3.
2. M1 con historial FPL: el mismo módulo `expected_minutes` alimentado con titularidades y minutos de FPL de los últimos 6 partidos, y congestión a 21 días solo de partidos de liga.
3. M1 con Sportmonks: el mismo módulo alimentado con las características del almacén de desarrollo (alineaciones de Sportmonks y congestión incluyendo copas y Europa).
La disponibilidad no entra en ninguna (el estado actual no se conoce antes del partido sin fugas).

| Versión | Brier (titular) | MAE minutos |
|---|---|---|
| Referencia (tasa base y media) | 0,1984 | 31,0 |
| 1 Regla simple FPL | 0,1637 | **19,1** |
| 2 M1 con historial FPL | 0,1517 | 21,6 |
| 3 M1 con Sportmonks | **0,1499** | 22,7 |

Diferencias con intervalo de confianza del 95 % (bootstrap por filas): Brier de M1-FPL menos simple −0,0120 [−0,0161, −0,0080]; Brier de M1-Sportmonks menos M1-FPL −0,0019 [−0,0040, +0,0001]; MAE de M1-FPL menos simple +2,5 min [+2,1, +2,9]; MAE de M1-Sportmonks menos M1-FPL +1,1 [+0,9, +1,3].

Por jornada (Brier simple, M1-FPL, M1-Sportmonks): GW2 0,157, 0,137, 0,132; GW3 0,149, 0,135, 0,134; GW4 0,165, 0,147, 0,142; GW5 0,171, 0,167, 0,166; GW6 0,169, 0,164, 0,164; GW7 0,170, 0,155, 0,157. La ventaja de M1 se estrecha en GW5 y GW6.

**Lectura.** M1 predice mejor **si** es titular que la regla simple (claro con el intervalo). Para **minutos** gana la regla simple. Sportmonks no añade nada fiable sobre M1 con FPL en titularidad (el intervalo toca 0) y empeora algo los minutos. Esto matiza Q5: allí dije que M1 no ganaba a la regla simple; para titularidad sí gana, para minutos no. Las dos versiones de M1 difieren de forma sistemática (|diferencia| superior a 0,01 en 1.277 de 1.503 filas); vienen de la pertenencia a plantilla (la tabla de Sportmonks es solo la actual) y de la congestión con copas y Europa, y no se ha aislado cuánto es cada una. Limitaciones: intervalos por fila (los jugadores de un mismo partido no son independientes) y rival sin controlar.

## D. Aviso de rotación en el calendario (#464)

Cambio de **solo texto**, en el PR #474 (borrador) que apunta a la rama de #464: la celda dice «3 días tras Champions League» (nombre accesible del hueco dorado; el número visible sigue siendo «3d» porque el hueco es estrecho) y el detalle dice «Su equipo jugó Champions League hace 3 días. Todavía no hay evidencia suficiente para cuantificar el riesgo de rotación.» Días, bandera y competición siguen viniendo del servidor sin cambios. Pruebas: jest 742 de 742 y tsc limpio.

El apoyo de datos a esa redacción: titularidad habitual del 76 % con descanso de hasta 3,5 días y del 76 % con más de 8 (n=119 y n=178, Q4); tras Europa unos 0,3 cambios más de once por par (0,6 si solo se miran los equipos europeos), con n=12 (Q6); y B de este informe.

## Qué no se pudo hacer

- Probar la anticipación con marcas de tiempo: la captura no las tiene por alineación (solo GW6-último y GW7). Todo queda retrospectivo.
- La comprobación inversa de Miley y Dedić (Dedić no ha vuelto al once).
- Aislar cuánto de la diferencia entre M1 con FPL y M1 con Sportmonks viene de la pertenencia a plantilla y cuánto de la congestión.
- Estadísticas por jugador de Sportmonks (la tabla de la captura está vacía), alineaciones de copas y Europa, y bajas anteriores al 11 oct.

## Correcciones respecto a los mensajes enviados durante el trabajo

- J: ya no son 23 pares sino 21 (sin los dos fichajes). Las cifras del mensaje original (20 y 17 de 23) pasan a 18 y 15 de 21.
- L: el mensaje decía que la relación con ausentes aparecía en 4 de 5; son 5 de 5. "Unos 10 llamadas" eran 10 llamadas más la repetición de Barcola V2.
- Q8: queda en 21 relaciones.
