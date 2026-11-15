# Clip 01: capturas reales

Capturado el **15 nov 2026**, con la J10 cerrada y antes del deadline de la J11 (21 nov, 11:00 UTC).

- **App:** `packages/fpl-ui` (Next.js) en local, contra el backend de producción (`fpl-backend-production-4151.up.railway.app`) y la API de FPL. El login (Clerk/Patreon) se simuló **solo en una copia temporal fuera del repo**, con tier free. En el repo no hay ningún cambio de autenticación.
- **Equipo FPL:** 330340 (N.Jackson es titular). Lo indicó Leo, porque Jackson no está en el 68643.
- **Dispositivo:** Chromium, viewport móvil 390×844 a 3x (PNG 1170×2532), locale `es-ES`, UI en español.
- **Pregunta enviada (1 mensaje de cuota):** el botón del Squad "Asistente →" envía "Cuéntame sobre N.Jackson — ¿lo alineo esta semana?".
- **Respuesta:** `jackson-answer-response.json` es el cuerpo exacto que devolvió `/api/proxy` (HTTP 200).

| Archivo | Qué muestra | Pasada |
|---|---|---|
| `00a-home.png` | Pantalla de inicio (Chat) con el campo "ID de equipo FPL" vacío | 3 (sin cuota) |
| `00b-id-typed.png` | ID 330340 escrito, antes de tocar "Conectar" | 3 |
| `id-entry/` | Foco en el campo, un PNG por dígito (1…6) y "Conectando…" | 3 |
| `00c-squad-after-connect.png` | Squad tras conectar y tocar la pestaña SQUAD | 3 |
| `video/flow-connect.mp4` | Inicio → escribir el ID → Conectar → Squad | 3 |
| `01-squad.png` | Squad en el campo, J10 | 1 (en vivo) |
| `02-jackson-detail.png` | N.Jackson tocado: mini ficha (11 Pts GW · 31.4% Sel. · 8.8 Forma) y "Asistente →" | 1 |
| `03-question-sent.png` | Burbuja de la pregunta y "Pensando…" | 1 |
| `04-answer-verdict.png` | Veredicto: "Cruce zonal favorable: SUN, IPS, EVE" · "Titular en 9 de 10" | 2 |
| `05-answer-player.png` | Ficha: 54 pts, £7.1m, 31.4%, forma 8.8, xG/xA… | 2 |
| `06-answer-fixtures.png` | Calendario J11–J14 e inicio de Zonas | 2 |
| `07-zonas.png` | Zonas: 57% área centro y 27% área izq; Cruce favorable con SUN, IPS y EVE | 2 |
| `07b-zonas-live.png` | Las mismas Zonas, pasada en vivo | 1 |
| `08-answer-end-live.png` | Final de la tarjeta (aviso de muestra corta y "Seguir conversación") | 1 |
| `video/flow-live.mp4` | Flujo completo en vivo, 42 s | 1 |
| `video/flow-scroll-replay.mp4` | Flujo completo con scroll lento desde el veredicto hasta Zonas, 25 s | 2 |

**Pasada 2:** al recibir la respuesta, la app baja sola hasta el final, así que en la pasada 1 no se grabó el recorrido por la tarjeta. Para no gastar otra pregunta, la pasada 2 repite el mismo flujo en la app real y entrega a `/api/proxy` **la misma respuesta guardada** (sin modificar). Las cifras de las dos pasadas coinciden.

**Privacidad:** en la cabecera del chat aparece el nombre del equipo 330340 con el nombre de su mánager truncado ("Los 11 impostores (Gerar…"). Los encuadres del storyboard lo dejan fuera; en el video habría que recortarlo o desenfocarlo.

**Pasada 3 (sin cuota):** el inicio de la app, la escritura del ID dígito a dígito y la conexión. Las preguntas al asistente se bloquearon en esta pasada, así que no se gastó cuota. En la app, el cambio de Chat a Squad es instantáneo al tocar la pestaña, sin animación de deslizamiento.
