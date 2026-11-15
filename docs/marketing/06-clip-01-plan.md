# Clip 01: "Toca. Pregunta. Entiende." Plan de producción

Estado: storyboard para aprobación (Leo). No se anima nada hasta aprobarlo.
Base: `05-storyboard-creative-base.md` + método del video de referencia (carpeta de assets, storyboard aprobado, transformaciones sin cross-dissolve, foco al centro, sonido al final, voz ajustada a la duración).

## Correcciones al borrador de NotebookLM
| Borrador | Problema | Corrección |
|---|---|---|
| Zonas "defensivas" | La tarjeta del jugador muestra **dónde dispara él** (`PlayerZonesPitch`), no zonas defensivas | Usar `PlayerZonesPitch` con el chip "Cruce favorable" |
| Squad → Zonas → CaptainCard | Son **dos respuestas distintas** de la app (ficha de jugador y `/capitan`). Juntarlas en 15s inventa un flujo que no existe | Clip 01 = un flujo real (Squad → Consultar a mi asistente → ficha con Zonas). El capitán va en el clip 02 |
| Botón "Consultar Asistente" | No existe | Botón: **"Consultar a mi asistente →"** (`sq.ask`, cambio pedido a Cerebro) |
| Sello "FAVORITO / DIFERENCIAL" cualquiera | Sería un dato inventado | Mostrar solo lo que devuelva la app para el jugador elegido |
| "No decidas a ciegas" | Encuadre negativo (regla del producto: positivo) | "Toca a cualquier jugador." |
| Texto genérico de producto | Promete sin enseñar | Cada frase coincide con lo que se ve en pantalla |

## Concepto
Un solo gesto real del producto, contado en 3 tiempos: **Toca → Pregunta → Entiende.** La emoción está en ver dos mapas cruzarse y encenderse en turquesa.

## Especificaciones
- 1080×1920, 30 fps, **15 s (450 frames)**. Captions incrustados, ES.
- Zona segura: el contenido clave entre y=280 e y=1500 (sin taparse con la UI de TikTok/Shorts).
- Ancla: **centro exacto (540, 900)**. Todo nace, cambia y muere ahí.
- Movimiento permanente: cámara con push-in lento (escala 1.00→1.06 por plano) y parallax del césped desenfocado al fondo.
- Texto: Barlow 700 (frases), Archivo Black (cifras). Entrada palabra a palabra slide-up de 24px, 6 frames por palabra, ease-out. Sin rebotes ni fade de letras.
- Sin cross-dissolve: cada transición es un **objeto que se transforma** en el siguiente.

## Storyboard (5 planos)
| # | Frames / s | Imagen (centro) | Transformación hacia el siguiente | Texto |
|---|---|---|---|---|
| 1 Hook | 0–60 · 0–2s | Ficha circular de un jugador (estilo `SquadPitch`) palpitando sobre fondo `#12111a`; 3 fichas más entran desde los bordes y se ordenan en formación | La cámara retrocede y las fichas **se asientan en el césped** → equipo completo | **"¿Lo alineo esta semana?"** |
| 2 Toca | 60–150 · 2–5s | Squad completo sobre el césped `#0f3320`; un pulso toca al jugador del centro, que crece y se aísla | La ficha **se despliega hacia abajo** en la mini ficha (Pts GW / Sel. / Forma) con el botón coral **"Consultar a mi asistente →"** | "Toca a cualquier jugador." |
| 3 Pregunta | 150–240 · 5–8s | Se pulsa "Consultar a mi asistente →". El botón **se estira y se convierte en la burbuja del chat**, donde se escribe: "Cuéntame sobre {jugador}, ¿lo alineo esta semana?" | La burbuja **se pliega en un rectángulo** que se dibuja como el área del campo (líneas de `PitchGeometry`) | "Pregúntale a tu asistente." |
| 4 Entiende (hero) | 240–375 · 8–12.5s | `PlayerZonesPitch`: las celdas se rellenan, el % sube en Archivo Black (p. ej. 0→59%), aparece la línea del rival y **la celda coincidente se enciende en turquesa** + chip "Cruce favorable" | Las líneas del campo **se recogen al centro** y forman el contorno del logo | "Dónde dispara él. Dónde concede el rival." |
| 5 CTA | 375–450 · 12.5–15s | `logo-icon.png` (real) se asienta en el centro con un brillo; debajo, pastilla coral | — (último fotograma fijo 0.5 s para el loop) | **"FPL Asistente · Prueba gratis"** + "benditofantasy" |

Profundidad de campo: el fondo (césped/UI secundaria) con blur de 12–18px; el objeto central siempre nítido.

## Datos en pantalla (regla de honestidad)
- Usamos **un jugador real con su respuesta real de la app** en la jornada de publicación (captura de la respuesta del backend guardada en `data.json` dentro del proyecto de video). Nada de cifras inventadas.
- Ni Salah ni De Bruyne. El jugador lo elige Leo según la jornada.

## Producción técnica (recomendación)
**Remotion dentro del repo** (`packages/fpl-promo/`):
- Reutiliza los tokens de `tailwind.config.ts`, las fuentes y la geometría de `PitchGeometry.tsx`, para que la UI se vea **idéntica a la app** (tip 1 del video: activos reales, no imitaciones).
- La animación se define con fotogramas exactos, así que la duración es fija y la voz y la música se ajustan a ella.
- Se renderiza a MP4 aquí mismo con Chromium (ya instalado), sin licencias.
- Desventaja: no ofrece 3D tipo Blender. Para una app de datos 2D no hace falta.

## Orden de trabajo
1. **Leo aprueba este storyboard** (o pide cambios). ← estamos aquí
2. Assets: logo en alta (SVG ideal; si no, el PNG de 1078px), jugador elegido + su respuesta real.
3. Animación v1 **sin sonido** → MP4 de revisión.
4. Iteración visual hasta aprobarla (los tiempos quedan fijos).
5. Sonido al final: pack de SFX (whoosh, tap, pop de celda, brillo de logo) y música de 15 s.
6. Voz opcional: guion ajustado a 15 s. Puede ser la voz del podcast (lo más auténtico) o una voz IA.
7. Exportar con variantes: sin voz (texto) y con voz.

## Decisiones pendientes de Leo
1. ¿Aprobado el cambio: clip 01 = Squad→Zonas y clip 02 = capitán?
2. Jugador protagonista (debe tener un "Cruce favorable" real esa jornada).
3. ¿Hay logo en SVG / wordmark "Bendito Fantasy"?
4. Audio: ¿voz de Leo/podcast, voz IA o solo música + texto?
5. ¿Tenemos SFX o música con licencia, o los buscamos (Artlist, etc.)?

## Decisiones de Leo (15 nov)
1. ✅ Separar: clip 01 = Zonas, clip 02 = capitán.
2. ✅ Protagonista: **N. Jackson (AVL)**. Buen calendario y se puede extender con Europa. Pendiente: capturar su respuesta real en la app (ficha + Zonas) en la jornada de publicación y confirmar que sale "Cruce favorable". Si no sale, se cambia de jugador o de jornada; no se inventa.
3. ✅ Logo: PNG por ahora; Leo entrega el SVG antes del corte final.
4. ✅ Música sí. Voz: Leo o voz IA (ver propuesta abajo).
5. ⏳ Cambio de copy "Ask AI" → "Consultar a mi asistente" enviado a Cerebro. Pendiente decidir "IA activa".

## Dirección de audio (propuesta)
- **Música:** el lo-fi encaja con "entender con calma", pero los cortes del clip piden pulso. Propuesta: **lo-fi con golpe**. Una pista de lo-fi de la carpeta de Leo a ~85–95 BPM, con los cambios de plano en los tiempos fuertes y un acento (kick/clap) en el momento del "Cruce favorable" (plano 4). Alternativa más enérgica para el clip 02 (capitán/deadline): electrónica minimal o afro-house a 115–120 BPM.
- **SFX (pocos y suaves):** tap en la ficha, whoosh corto en cada transformación, "pop" por celda de zona, campanita/brillo en el turquesa y en el logo.
- **Voz (recomendación: Leo):** la comunidad del podcast ya conoce su voz, y eso refuerza "asistente de Bendito Fantasy" frente a "una IA más". Se graba con el móvil en un cuarto con ropa/cortinas, a 15–20 cm, en 3 tomas, y se limpia después. Plan B: voz IA cálida en español (p. ej. ElevenLabs), que requiere cuenta/API key.
- **Guion VO (15 s, ~32 palabras):**
  > ¿Lo alineo esta semana? · Toca a Jackson en tu equipo. · Consulta a tu asistente. · Mira dónde dispara él… y dónde concede su rival. · Ahí está el cruce favorable. · FPL Asistente. Pruébalo gratis.

## Datos confirmados: N. Jackson (captura de Leo, 15 nov, antes de la GW11)
Fuente: `clip-01/data.json` y capturas en `clip-01/ref/`.
- ✅ Cruce favorable real en las GW11–13: **Sunderland (H)** en área centro + área izq; **Ipswich (A)** y **Everton (H)** en área centro.
- Zonas: **57%** de su xG sin penalti en el área centro y **27%** en el área izquierda. Las dos casillas salen en turquesa.
- Plano 4 usa la **GW11 vs Sunderland**: es el único rival que enciende las dos casillas. El 57% sube primero y el 27% después.
- Mini ficha del plano 2: 54 pts · forma 8.8 · 31.4% sel. · £7.1m.
- Guion VO ajustado: "Mira dónde dispara él… y dónde concede Sunderland."
- Texto en pantalla en ES (las capturas están en EN): "Área centro · 57% de su xG sin penalti", "Cruce favorable".
- Vigencia: el clip debe publicarse **antes del deadline de la GW11**, o se actualiza con el siguiente rival.

## Storyboard visual con capturas reales (15 nov, pendiente de aprobación)
- Jackson no está en el equipo 68643. Leo indicó usar el **330340**, donde es titular.
- Capturas de la app real (backend de producción, J10 cerrada, antes del deadline de la J11): `clip-01/captures/` (ver su README).
- Storyboard: `clip-01/storyboard/index.html`, `contact-sheet.png` y `frames/shot-0N.png` (1080×1920).
- La respuesta real coincide con `data.json`: 57% área centro, 27% área izq y "Cruce favorable · Área centro, Área izq" contra Sunderland (L) en la J11.
- Mini ficha del plano 2: muestra **11 Pts GW** (puntos de la J10), no 54. Los 54 pts totales salen en la ficha de la respuesta.
- No se produce el video hasta que Leo apruebe.

### Cambio de Leo (15 nov): del 3 al 4 es un scroll, no un morph
- Del 3 al 4 se muestra **la misma pantalla de la app**: pregunta → respuesta → scroll real hasta Zonas. Desaparece el morph de "Pensando…" al área del campo.
- "Pensando…" aparece solo ~0.4 s. La app tarda más, pero el clip no espera.
- Tiempos nuevos: 3a Pregunta 5–6.3 s · 3b Respuesta (veredicto) 6.3–7.5 s · 3c Scroll con desenfoque de movimiento 7.5–8.5 s · 4 Zonas 8.5–12.5 s. El 1, el 2 y el 5 no cambian.
- En el plano 4, las cifras se muestran tal como salen en la captura, sin animarlas de 0 a 57%. El énfasis lo hacen el push-in y el brillo en la fila de Sunderland.

### Cambio de Leo (15 nov): empezar en la pantalla de inicio
- El clip abre en el inicio real de la app: enfoca el campo del ID, se escriben los dígitos (3-3-0-3-4-0) y se toca "Conectar". Al tocar la pestaña SQUAD aparece el equipo en la cancha, y desde ahí sigue lo que antes era el plano 1.
- El hook en texto, "¿Lo alineo esta semana?", se mantiene en 0–2.5 s sobre la conexión. El plano del Squad pasa a decir "Tu equipo, en la cancha."
- Tiempos (15 s): 0a Inicio 0–1 · 0b Conecta 1–2.5 · 1 Squad 2.5–4 · 2 Toca 4–6 · 3a Pregunta 6–7 · 3b Respuesta 7–8 · 3c Scroll 8–8.8 · 4 Zonas 8.8–12.8 · 5 CTA 12.8–15.
- Logo: SVG oficial de Leo en `docs/marketing/assets/logo-bf.svg`, usado en el plano 5.
