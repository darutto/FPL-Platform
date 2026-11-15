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
