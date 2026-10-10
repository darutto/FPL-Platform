# i152 — mini-canchita en la sección «Zonas» de PlayerCard

Solo UI, sin datos nuevos (`zones[].share` y `fixtures[].matches` ya llegan en `player_snapshot.zonal`). **No fusionar hasta que Leo cierre el gate de i148 en prod.**

## Qué cambia
- `PitchGeometry.tsx` (nuevo): la geometría del área (contorno, área pequeña, portería, guías de tercios, punto y arco) extraída **tal cual** de `DefensiveZonesCard`, junto con `ZONE_X/ZONE_WIDTH/ZONE_CENTER_X`.
- `PlayerZonesPitch.tsx` (nuevo): dibuja las **seis** zonas del motor. El SVG original solo cubría los tres tercios del área; aquí se añade debajo la franja frontal (borde del área) con los mismos tercios, así caben las seis (Área/Frontal × izq/centro/der). Ninguna zona queda fuera.
- `pitchCell` (en `lib/defensive-zones.ts`): clave del motor → celda (fila área/frontal, columna izq/centro/der); claves desconocidas → `null` y no se dibujan.
- `PlayerZonasSection.tsx`: la canchita (116 px) a la izquierda de los chips; una línea de leyenda («Turquesa: coincide con la zona débil de un rival favorable») solo si hay algún cruce favorable.

## Reglas
- Turquesa = la zona del jugador coincide con `matches` de un partido `favorable`; gris neutro = zona del jugador sin coincidencia; nada en rojo; las zonas que no son del jugador no se pintan.
- Sin zonas (o ninguna colocable) → sin canchita (ni su contenedor). Sin favorables → solo las zonas del jugador, todas neutras. `matches` de partidos no favorables nunca resaltan.
- `share` (0–1) solo gradúa el tono; el texto de cada celda usa la única conversión `sharePercent`.
- `aria-label`: «Área centro: 59% de su xG (coincide con un cruce favorable) · Frontal der: 26% de su xG».

## Verificación
- **DefensiveZonesCard idéntica:** `__tests__/defensive-zones-markup.test.tsx` (3 snapshots de `innerHTML`: zonas mixtas, todas medias, todas oportunidad con procedencia). El snapshot se grabó **antes** de extraer la geometría y pasa sin cambios después.
- `player-zones-pitch.test.tsx` (18 tests): las seis zonas distintas y bien colocadas, solo las del jugador, con y sin coincidencias, sin favorables, coincidencia en zona ajena, matches de partido no favorable, sin zonas, zonas no colocables, aria, % una sola vez, sin rojo, graduación del tono, integración en `PlayerCard`.
- Mutaciones (`artifacts/i152-mutation-report.txt`): 15 mutantes (fila/columna intercambiadas, no favorables resaltan, colores, guardas de «sin zonas»/«no colocable», % sin convertir, aria sin coincidencia o sin porcentajes, leyenda siempre, contenedor sin guarda, geometría compartida alterada ×2, tono sin escala): **15 muertos, 0 vivos**.
- `tsc --noEmit` limpio; jest completo 49 suites / 676 tests / 3 snapshots en verde.
- Capturas (misma receta de harness que `2026-10-09-b10-ui-report.md`, puerto 4317; móvil = iframe de 390 px reales):
  - `i152-pitch-palmer-prod-{desktop,mobile}.png`: payload real de prod de Palmer (`b10-prod-ask-palmer.json`): una zona, «Área centro 59 %», coincide con J8 Tottenham → turquesa.
  - `i152-pitch-three-zones-synthetic-{desktop,mobile}.png`: **sintético** (el payload de Palmer con tres zonas coherentes —34 %, 27 %, 26 %: suman 87 %— y dos coincidencias, una de ellas frontal); no son datos reales.

## Salvedades
- Con el payload real hoy el jugador tiene una sola zona, así que la canchita luce sobria. El backend solo lista zonas con ≥ 25 % del xG sin penalti, así que en datos reales caben como mucho 4 zonas a la vez (y nunca suman más de 100 %); las seis celdas están cubiertas por los tests, no por una captura, porque una captura con seis zonas visibles no sería coherente con los datos.
- Ajuste tras la revisión: el porcentaje de la celda del área baja 24 unidades del centro (antes 9) para no quedar pegado a la portería.
- La canchita es pequeña a propósito (116 px): los porcentajes van dentro de las celdas y los chips al lado repiten los números.

## Ronda 2 (petición de Leo, 10-oct): canchita más grande y ampliable

- **Tamaño:** la mini pasa de 116 a 220 px de ancho al lado de los chips (≥ 481 px); en ≤ 480 px se apila encima de los chips a todo el ancho de la sección. Sin scroll horizontal a 390 px (captura móvil).
- **Botón accesible:** `PlayerZonesPitchExpandable`: `<button type="button">` con `aria-label="Ampliar zonas de <jugador>"`, `aria-haspopup="dialog"`, `aria-expanded` y anillo de foco visible.
- **Vista ampliada** (`role="dialog"`, `aria-modal`, `aria-labelledby`, portal a `document.body`): la misma `PlayerZonesPitch` (variante `large`, mismo `PitchGeometry`; no se duplica el SVG) con las mismas zonas y colores, la lista de zonas con sus porcentajes y la misma leyenda (`PITCH_LEGEND`, solo si hay favorable). **Solo datos del jugador**: sin selector por rival ni zonas del rival (los cruces ya están en el texto y en las filas).
- **Cierre:** X, Esc o tocar fuera del panel (no dentro). Foco: entra en la X al abrir, queda atrapado (Tab/Shift+Tab, incluso si el foco se escapó) y vuelve a la canchita al cerrar por cualquiera de las tres vías; el `preventDefault` en el mousedown del fondo evita que el navegador lo mande a `<body>`. El scroll del fondo se bloquea y se restaura (también al desmontar abierto).
- **Escritorio / móvil:** ventana centrada de hasta 640 px sobre el chat; ≤ 480 px pantalla completa (solo variantes CSS del mismo diálogo).

### Verificación ronda 2
- `player-zones-pitch-dialog.test.tsx` (17 tests): botón (nombre, `aria-*`, foco visible, teclado), layout responsive, apertura como diálogo modal, solo-jugador (sin combobox/tab/radio, sin nombres de rival, un único botón), mini y ampliada con las mismas celdas y colores, leyenda condicional, cierre con X/Esc/fuera (y no dentro), foco dentro y retorno por las tres vías, trampa de foco, bloqueo y restauración del scroll (incl. desmontaje), variantes de escritorio y móvil.
- Mutaciones de las guardas (`artifacts/i152-dialog-mutation-report.txt`): 20 mutantes (etiqueta sin jugador, sin anillo de foco, Esc/fuera/X sin cerrar, clic dentro cierra, foco sin devolver o sin entrar o sin trampa, scroll sin bloquear o sin restaurar, sin `aria-modal`/`aria-labelledby`, grande con una zona menos o sin el favorable, % sin convertir, leyenda siempre, layout móvil o 220 px o pantalla completa roto): **20 muertos, 0 vivos**.
- `DefensiveZonesCard`: los 3 snapshots siguen pasando sin cambios. jest completo 50 suites / 693 tests / 3 snapshots en verde.
- `tsc`: el código fuente compila; el único ruido son los tipos generados de `.next` de las páginas de captura ya borradas (caché de `next dev`, no versionada).
- Capturas con el payload real de prod de Palmer (`b10-prod-ask-palmer.json`; las anteriores de la ronda 1 se retiran): `i152-v2-mini-desktop.png`, `i152-v2-zoom-desktop.png` (ventana sobre el chat, foco visible en la X), `i152-v2-mini-mobile.png` (390 px, canchita a todo el ancho encima de los chips), `i152-v2-zoom-mobile.png` (pantalla completa). El móvil es un iframe de 390 px reales; la ampliada se abre con un clic automático de la página de captura (receta de harness como en `2026-10-09-b10-ui-report.md`).
