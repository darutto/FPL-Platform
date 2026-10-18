# Prueba de capacidad de los datos, sin LLM: preguntas Q1 a Q8 (18 oct 2026)

Encargo aprobado por Leo el 2026-10-18. Cada pregunta se responde directamente desde los datos con scripts propios (`packages/football-intelligence/scripts/data_capability_q1_q8/`), sin modelo de lenguaje. Descriptiva sobre el pasado: sin congelado ni sello. Cero llamadas nuevas a Sportmonks; las llamadas a la API pública de FPL (bootstrap y `element-summary`) sí se hicieron.

Escrito para: Leo y el revisor, para validar los hallazgos con Sofascore o la tele.

## Datos y límites (léase antes de las tablas)

- **Alineaciones de liga, GW1 a GW6** (Sportmonks, almacén local del trial, construido el 13 oct) **más el sábado de GW7** (5 partidos con once confirmado y rejilla, de `lineup-watch/gw7.ndjson`). Los minutos y las titularidades de GW7 salen de FPL.
- **Copas y Europa: solo calendario.** La captura trae fechas y estados de Carabao Cup, Champions, Europa League, Conference y Supercopa, pero **ninguna alineación** de esos partidos. Por eso no cuentan como titularidades ni sirven para medir rotación dentro de ellos; solo para descanso y congestión.
- **La captura es del 12 y 13 oct.** Los partidos europeos del 13 al 15 oct figuran como "no jugados" y los he tratado como jugados por su hora. Es una inferencia.
- **Qué es la "posición" de Sportmonks aquí.** En los 1.318 titulares de liga de GW1 a GW6, la posición detallada (Centre Back, Left Midfield, etc.) es una función exacta de tres cosas: la formación, la casilla de la rejilla y si el equipo juega en casa o fuera (99 combinaciones, ninguna excepción). Es un hecho del once inicial anunciado, no un mapa de calor. La banda izquierda o derecha sale de la columna de la rejilla y del lugar del partido. Para el sábado de GW7, que solo trae rejilla, la posición se reconstruye con esa tabla.
- **Hecho crudo contra estimación del módulo.** Hecho crudo = formación, casilla, posición detallada, minutos, titularidad. Estimación nuestra = `role-map-v3` (convierte posición en rol: Left/Right Midfield pasa a extremo, Attacking Midfield a `attacking_midfield`) y M1 (`expected_minutes`, coeficientes a mano).
- **Equipos muy estables.** 72 % de las titularidades se juegan en 4-2-3-1; los 20 equipos usan solo cinco formaciones. Eso limita cuántos cambios de rol puede haber.
- **Ventanas.** "Últimos 3 partidos contra los 3–4 anteriores", en partidos de liga. Entre GW5 y GW6 hay unos 21 días por el parón de selecciones. Abstención por debajo de 3 titularidades por ventana. En cada hallazgo, n = titularidades o partidos.
- **Nombres.** Todos los jugadores citados están en el bootstrap actual de FPL (comprobado). Salah no aparece, como se sabe. Sin ids de proveedor ni cargas crudas en git.
- **Puntuación** (1 a 5): información nueva, interpretación, base. "Valor para el usuario" lo rellena Leo.

## Resumen

| Q | Pregunta | Hallazgo | Nueva info | Interpretación | Base | Valor |
|---|---|---|---|---|---|---|
| 1 | Defensas más adelantados | 12 defensas estables en casilla avanzada, 12 puntuales, de 131 | 4 | 3 | 4 | Leo |
| 2 | Cambio de rol o banda | 9 de 127 cambian; 5 son individuales, el resto cambios de formación del equipo | 4 | 2 | 4 | Leo |
| 3 | Cambio de rol y xG | los 9 tienen un delta de xGI/90 positivo; 6 por encima del percentil 80 del control | 3 | 2 | 3 | Leo |
| 4 | Titulares que pierden minutos | 33 de 178 titulares habituales; 24 sin ninguna señal en FPL; el calendario no explica el conjunto | 3 | 2 | 3 | Leo |
| 5 | Riesgo de minutos contra puntos | 11 de 74 jugadores de puntos altos tienen riesgo alto según M1; M1 no mejora lo simple | 3 | 3 | 3 | Leo |
| 6 | Once tras Europa | 1,92 cambios por par tras Europa contra 1,62 solo liga (n=12 y 48); no es significativo | 3 | 2 | 2 | Leo |
| 7 | Rol tras ausencia | sin asociación global; 10 casos de relleno del hueco | 3 | 3 | 3 | Leo |
| 8 | Quién gana minutos | 23 de 33 salidas tienen un sustituto directo en el mismo hueco; casi todos con <3 % de propiedad | 4 | 3 | 3 | Leo |

## Q1. Defensas que juegan más adelantados que su posición

**(a) FPL solo.** Ve la salida: de los defensas estables en casilla avanzada, mediana de xGI/90 0,21 contra 0,07 del resto, amenaza/90 11,4 contra 4,7, contribución defensiva/90 4,8 contra 7,7. No distingue carrilero, lateral o extremo.

**(b) Sportmonks añade.** Formación y casilla del once en cada partido. **(c) Interpretación.** 131 defensas FPL con alguna titularidad (GW1 a GW6 más el sábado de GW7). Estable = al menos 3 titularidades en casilla avanzada y al menos la mitad de las suyas; puntual = 1 o 2. Resultado: 12 estables, 12 puntuales, 107 de línea defensiva pura.

**(d)(e) Evidencia (n = titularidades; entre paréntesis las avanzadas).**

| Jugador | Equipo | Avanzadas | Qué hace | Salida FPL (xGI/90) |
|---|---|---|---|---|
| De Cuyper | BHA | 6 de 6 | banda de los tres mediapuntas del 4-2-3-1 (zona de extremo) | 0,45, el mayor de todos los defensas |
| Bogle | LEE | 6 de 6 | carrilero en 3-4-2-1 | 0,32 |
| Gudmundsson | LEE | 4 de 4 | carrilero en 3-4-2-1 | 0,08 |
| N.Williams | NFO | 6 de 6 | carrilero | 0,25 |
| Muñoz | NFO / CRY | 4 de 4 | carrilero (3 con NFO y 1 con CRY) | 0,37 |
| Mitchell | CRY | 6 de 6 | carrilero | 0,19 |
| Khalaili | CRY | 5 de 5 | carrilero | 0,32 |
| James | CHE | 3 de 3 | casilla de centrocampista central | 0,18 |
| Meunier | SUN | 4 de 6 | banda de los tres mediapuntas | 0,22 |
| Hato | CHE | 3 de 5 | carrilero | 0,06 |
| Aina | NFO | 3 de 5 | carrilero | 0,14 |
| Dasilva | COV | 3 de 6 | carrilero | 0,18 |

Puntuales: O'Reilly (MCI) 2 de 4 (centrocampista central y mediapunta), Gusto (CHE) 2 de 3, Hume (SUN) 2 de 3, Justin (LEE) 2 de 6, Chavarria (CHE) 2 de 2 (muestra mínima).

Nota: "carrilero" aquí significa estar en una casilla de ala dentro de una línea de 3 centrales. El dato da formación y casilla; no cuánto sube.

## Q2. Cambio de rol o banda: últimos 3 contra los 3–4 anteriores

**(a) FPL solo.** La posición es fija. **(b) Sportmonks.** Rol y banda por partido. **(c) Interpretación.** De 127 jugadores con al menos 6 titularidades, 9 cambian. El resto (205 de 332) se abstiene por no llegar a 3 titularidades por ventana.

**(d)(e) Evidencia (n previa / últimas 3).**

Individuales, con la formación del equipo estable:
- **Iwobi (FUL, MID):** de centrocampista central (3 de 4) a extremo izquierdo (3 de 3).
- **Meunier (SUN, DEF):** de lateral derecho (2 de 3) a extremo derecho (3 de 3).
- **L.Miley (NEW, MID):** de centrocampista central (4 de 4) a lateral derecho (3 de 3). Un centrocampista de FPL jugando de lateral.
- **Kamada (CRY, MID):** de centrocampista central (2 de 3) a mediapunta (3 de 3).
- **Buendía (AVL, MID):** alterna extremo izquierdo y mediapunta; señal débil.

Cambios de formación del equipo, no atribuibles al jugador: O'Shea (IPS, de lateral derecho a central, IPS pasó a 3-4-2-1 en GW7), Dasilva (COV), Justin y Stach (LEE).

## Q3. ¿Coinciden esos cambios con subidas o bajadas de xG o amenaza?

**(a) FPL solo.** Ve la subida de xGI/90 pero no la causa. Mediana del cambio en el control (118 jugadores que no cambian de rol): 0,00 de xGI/90, rango intercuartil de −0,12 a +0,07. **(b) Sportmonks.** El cambio de hueco justo antes. **No hay estadísticas por jugador de Sportmonks**: la tabla de estadísticas de jugador por partido de la captura tiene 0 filas. Uso xG, xA y amenaza de FPL.

**(c) Interpretación.** Solo asociación. Los 9 cambiantes tienen un delta de xGI/90 positivo; 6 por encima del percentil 80 del control. No es un efecto: el cambio de rol puede llegar después de una racha buena.

**(d)(e) Evidencia (xGI/90 previa a última; minutos de la ventana última; percentil en el control).**

| Jugador | Cambio | xGI/90 | Minutos | Percentil |
|---|---|---|---|---|
| Iwobi (FUL) | mediocentro a extremo izquierdo | 0,27 a 0,73 | 246 | 100 |
| Meunier (SUN) | lateral a extremo derecho | 0,13 a 0,35 | 186 | 92 |
| Kamada (CRY) | mediocentro a mediapunta | 0,12 a 0,30 | 262 | 88 |
| Justin (LEE) | extremo a central | 0,06 a 0,22 | 258 | 85 |
| Buendía (AVL) | mediapunta a extremo | 0,27 a 0,38 | 224 | 81 |
| Dasilva (COV) | alterna lateral y extremo | 0,11 a 0,24 | 270 | 81 |
| L.Miley (NEW) | mediocentro a lateral | 0,04 a 0,13 | 238 | sin señal |

Justin es el que contradice la intuición: juega más atrás y su xGI/90 sube. Muestra de 190 a 270 minutos por ventana, sin control de rival ni de local o visitante.

## Q4. Titulares que pierden minutos y calendario que coincide

**Definiciones.** Titularidad = campo `starts` de FPL; minutos = FPL (`element-summary`). "Pierde el once" cuenta como no titular aunque entre de suplente. Los minutos 0 de las listas vienen de FPL. El calendario (descanso, Europa, copas) sale de Sportmonks.

**(a) FPL solo.** Ve minutos y estado. De 178 titulares habituales (al menos 75 % de titularidades previas en 3 o 4 partidos), 33 empezaron como mucho 1 de los últimos 3; en 24 FPL dice "disponible" sin noticia. **(b) Sportmonks.** Copas y Europa en el calendario y el descanso real entre partidos.

**(c) Interpretación.** El calendario **no explica** la pérdida de minutos en conjunto (534 partidos de titulares habituales). Tasa de titularidad: descanso hasta 3,5 días 0,76 (n=119); 3,5 a 5 días 0,85 (112); 5 a 8 días 0,78 (125); más de 8 días 0,76 (178). Tras Europa o copa 0,81 (n=211) contra 0,77 tras liga (323). Resultado negativo útil.

**(d)(e) Evidencia.** Titularidades previas a últimas 3, con FPL en "disponible" y sin noticia:
- Scherpen (IPS, portero) 4 de 4 a 0 de 3; Dedić (NEW) 4/4 a 0/3; Tel (TOT) 3/3 a 0/3; Barkley (AVL) 4/4 a 0/3; Lavia (CHE) 4/4 a 0/3; Stroud (HUL) 4/4 a 0/3; George (EVE) 4/4 a 0/3; M.Sangaré (BRE) 4/4 a 0/3.
- Con coincidencia de calendario: 0 minutos en el partido de liga 2,7 a 3,8 días después de una eliminatoria de Carabao para Scherpen, Khusanov (MCI), Collins (BRE), Röhl (EVE), Nketiah (CRY), Tel, Pau (AVL) y Foden (MCI). Hay sesgo de selección.
- Con un partido europeo en medio: Khusanov (MCI) jugó 14 minutos y Gvardiol (MCI) 29 minutos en el partido de liga 2,8 días después de la Champions.
- Sale antes siendo titular (al menos 2 titularidades en 3 y 15 o más minutos menos): White (ARS) de 90 a 54 de media, Lewis-Skelly (ARS) 75 a 54, Schade (BRE) 89 a 70, Ndiaye (MCI) 89 a 73, Slater (HUL) 90 a 75. n de 2 o 3.
- Ya explicados por FPL (lesión o duda), fuera de los hallazgos: Milenković, Maatsen, James, Szoboszlai, Elanga, Mendy y otros.

## Q5. Riesgo de minutos distinto del que sugiere el historial de puntos

**(a) FPL solo.** Puntos por aparición, estado y noticia. 74 jugadores en el cuarto superior de puntos por aparición (4,27 o más, de 296 con al menos 3 apariciones). **(b) Sportmonks / M1.** Probabilidad de titularidad y minutos esperados, estimación del módulo con corte el 13 oct.

**(c) Interpretación.** 11 de esos 74 tienen minutos esperados de 60 o menos y FPL los muestra sin ninguna alerta.

**(d)(e) Evidencia.** Puntos por aparición, minutos esperados M1 (probabilidad de titular), apariciones y titularidades de 6:
- Bruno G. (ARS) 4,5; 24 min (0,19); 4 apariciones y 1 titularidad. El más claro.
- Dunk (BHA) 4,6; 40 (0,40); 5 (4).
- Gakpo (LIV) 6,4; 42 (0,44); 5 (4). El sábado no jugó.
- White (ARS) 5,2; 47 (0,62); 5 (5).
- Isak (LIV) 6,6; 50 (0,60); sábado titular 78 min y 9 puntos.
- Gvardiol (MCI) 6,8; 55 (0,60); sábado suplente 29 min.
- João Pedro (CHE) 9,0; 59 (0,69); sábado titular 90 min.

Validación sobre el sábado de GW7 (149 jugadores de 10 equipos, 99 titulares): Brier de M1 0,168, de la regla simple "titularidades de los últimos 3" 0,172, de la tasa base 0,223. **M1 no mejora la regla simple**; difieren en 11 casos y M1 acierta más en 5. M1 mezcla en `rotation_risk` dos cosas distintas: fatiga o rotación y haber perdido el puesto.

## Q6. Equipos que cambian el once tras partidos europeos

**(a) FPL solo.** No ve el partido europeo. **(b) Sportmonks.** Fecha de cada partido europeo y de copa; las alineaciones de esos partidos no existen en la captura.

**(c) Interpretación.** Sin efecto grande. 108 pares consecutivos de once completos, sin los pares posteriores al parón de selecciones. Cambios medios por par: Europa 1,92 (mediana 2; n=12), Carabao 1,50 (n=28), solo liga 1,62 (n=48). Solo en los 9 equipos europeos: solo liga 1,33 (n=18) contra Europa 1,92 (n=12). Sobre 0,6 cambios más por par; no significativo.

**(d)(e) Evidencia.** Casos tras Europa:
- **MCI, sábado GW7** (2,8 días tras Champions): 4 cambios. Salen Enzo, Semenyo, Cherki y Anderson; entran Foden, Doku, Kovačić y Bouaddi.
- LIV, sábado GW7: 2 cambios. Salen Gravenberch y Koumas; entran Szoboszlai e Isak.
- AVL, sábado GW7: 2 cambios. Salen McGinn y Ruggeri; entran Alysson y Wan-Bissaka.
- LIV 12 sep: 3 cambios (Kerkez, Gakpo y Mac Allister fuera). BHA 30 ago: 3 (Hinshelwood, Georginio y Ayari fuera).

Contraste fuera de Europa: TOT 10 oct, 6 cambios tras el parón; CHE 18 sep, 5 cambios con 6 días de descanso. ARS, con Champions, 0 cambios en su único par.

## Q7. Cambios de rol tras la ausencia de un compañero habitual

**(a) FPL solo.** Estado y minutos del ausente. **(b) Sportmonks.** Quién ocupa el hueco y de dónde viene. Datos de bajas (sidelined) de Sportmonks: 71 filas, instantánea del 13 oct, sin cobertura de las bajas de septiembre.

**Definición de ausente y de dónde sale.** Ausente = titular habitual (al menos 3 de los 4 partidos anteriores de su equipo) que **no juega ningún minuto** en el partido. Hasta GW6 el dato sale de los minutos de la alineación de Sportmonks (incluye suplentes que entraron). El sábado de GW7 Sportmonks solo trae el once, así que los minutos salen de FPL (`element-summary`); una primera versión usó solo el once y contó como ausentes a suplentes que sí jugaron (caso Schade, BRE, 45 minutos el 17 oct, y Fatawu, IPS), que se han retirado. Sin esa corrección el resultado era 37 partidos con ausente y 11 casos de relleno.

**(c) Interpretación.** Sin asociación global: con un habitual ausente (n=35 partidos) hay 0,63 titulares que cambian de rol por partido; sin ausente (n=15), 0,80. Sí se ven 10 casos en los que un jugador pasa exactamente al hueco habitual del ausente.

**(d)(e) Evidencia (entre paréntesis, si hay registro de baja).**
- BOU 10 oct: Rayan de extremo derecho a mediapunta, por Kluivert (lesión). BRE 10 oct: Lewis-Potter de lateral izquierdo a mediapunta, por Damsgaard (lesión).
- NEW 19 sep: L.Miley de centrocampista central a lateral derecho, por Dedić. Se mantiene en 3 partidos (es el cambio de Q2).
- IPS 19 sep y 10 oct: O'Shea de lateral derecho a central, por Greaves.
- NFO 11 oct: Aina a central, por Jair Cunha. EVE 11 oct: Branthwaite de central a lateral izquierdo, por Mykolenko. SUN 10 oct: Mukiele a central, por Ballard. TOT 19 sep: Marmoush de delantero a extremo izquierdo, por Tel. NEW 17 oct: Fernandez-Pardo de delantero a extremo derecho, por J.Murphy.

Cubrir el hueco en el mismo partido es casi mecánico; lo que añade el dato es quién lo cubre.

## Q8. Quién gana titularidades o minutos desde que un compañero sale del once

**(a) FPL solo.** Ve que uno juega más y otro menos. **(b) Sportmonks.** El hueco: si el que sube ocupa el puesto del que baja.

**Definición y fuente.** "Sale del once" = no figura entre los titulares (`starts` de FPL, no minutos): un jugador que entra de suplente cuenta como fuera del once. Los minutos por partido también son de FPL. El hueco (rol y banda) sale de la alineación de Sportmonks.

**(c) Interpretación.** Salida del once = titular habitual con como mucho 1 titularidad en los últimos 3 partidos (33 jugadores). 23 de los 33 tienen un sustituto en su mismo hueco que pasa de como mucho 1 titularidad en 3 a al menos dos tercios después. Casi todos con menos del 3 % de propiedad.

**(d)(e) Evidencia (titularidades antes a después; minutos por partido antes a después).**
- **Barcola (LIV, 2,9 %):** 0/3 a 4/4, 9 a 80 min; extremo izquierdo, por Gakpo. El caso más limpio: LIV solo tiene un ausente.
- Henderson (CHE, 0,9 %): 0/3 a 3/3, 0 a 90; centrocampista central, por James y Lavia. CHE tiene 5 ausentes: atribución doble.
- Benitez (CRY, portero, 0,1 %): 0/3 a 3/3, 0 a 90; por Henderson CRY. Walton (IPS, portero, 0,4 %): 0/3 a 3/3; por Scherpen.
- Diomande (NFO, 0,5 %): 0/3 a 3/3, 0 a 84; central, por Milenković y Jair Cunha.
- Matheus N. (MCI, 1,1 %): 0/3 a 4/4, 11 a 86; lateral derecho, por Khusanov. O'Reilly (MCI, 9,4 %): 0/3 a 2/2; lateral izquierdo, por Gvardiol.
- Maitland-Niles (EVE, 1,5 %) por Röhl; Grealish (EVE, 0,5 %) por George; Neto (CHE, 1,6 %) por Gusto.

n de 2 a 5 partidos después; en AVL, CHE e IPS no se puede atribuir cada beneficiario a un ausente. El dato no dice que seguirá.

## Qué implica para el aviso de rotación premium (#464)

El aviso salta con 3 días de descanso o menos tras un partido europeo o de copa. Q4 y Q6 lo apoyan poco. Q4: los titulares habituales empiezan un 76 % de los partidos con descanso de hasta 3,5 días (n=119), igual que con más de 8 días (76 %, n=178); tras Europa o copa 81 % (n=211) contra 77 % tras liga. Q6: tras Europa el once cambia 1,92 jugadores por par contra 1,62 solo liga, es decir unos 0,3 más (0,6 más si solo se miran los equipos europeos), con n=12 pares. Con estos datos el aviso no es falso, pero el efecto medio es pequeño y la muestra corta: convendría presentarlo como "posible rotación" y no como previsión, y mejor ligado al caso concreto del equipo (Manchester City, 4 cambios el sábado tras la Champions, es un ejemplo) que a la regla de los 3 días. Esta sección no cambia código.

## Qué falta

- `player_fixture_statistics` tiene **0 filas** en la captura: no hay estadísticas por jugador de Sportmonks (tiros, xG, pases). Q3 se hizo con xG y amenaza de FPL.
- **No se capturaron las alineaciones de copas y de Europa**: solo calendario. No se puede medir la rotación dentro de esos partidos ni quién jugó.
- El **snapshot de sidelined cubre solo el 13 oct**: las bajas de septiembre y las posteriores al 13 oct no están. Los partidos europeos del 13 al 15 oct figuran como no jugados en la captura.
- El sábado de GW7 trae solo once y rejilla (sin minutos ni suplentes).
- Cualquier captura adicional necesita el visto bueno de Leo; no se ha hecho ninguna.

## Qué hemos aprendido de los datos (no de un LLM)

1. **El valor está en el hueco del once, no en la estadística.** La posición de Sportmonks es una función de la formación, la casilla y el lugar del partido. Es un hecho fuerte y barato, y es lo que da Q1, Q2, Q7 y Q8.
2. **Los hallazgos de rol y de ausencias son verificables a mano** (Barcola por Gakpo, Henderson por Lavia, De Cuyper en banda, Iwobi de extremo). Los de calendario (Q4, Q6) no muestran un efecto general: el resultado negativo también es información.
3. **M1 no gana a una regla simple** en la única validación posible (Q5). Antes de venderlo como "riesgo de minutos" hace falta separar fatiga de pérdida de puesto.
4. **Lo que falta.** Alineaciones de Europa y copas (no están en la captura), estadísticas por jugador (la tabla está vacía) y bajas anteriores al 11 oct.

## Correcciones respecto a los mensajes enviados durante el trabajo

- Q3: en el mensaje dije "5 de 9 por encima del percentil 80". Son 6.
- Q4: en el mensaje atribuí 14 y 29 minutos a "Foden y Khusanov". Son Khusanov (14) y Gvardiol (29). Foden jugó 76 minutos en ese partido.
- Q5: una frase del mensaje sobre Bruno G. era confusa; el dato correcto es 4 apariciones y 1 titularidad.
- Q7: el mensaje contaba 37 partidos con ausente y 11 casos de relleno por usar solo el once en GW7 (Schade y Fatawu eran suplentes que jugaron). Corregido: 35 partidos, 0,63 contra 0,80 sin ausente (n=15), 10 casos.
