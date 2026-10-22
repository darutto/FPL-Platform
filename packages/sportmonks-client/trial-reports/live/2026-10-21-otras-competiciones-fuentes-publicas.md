# Propuesta: calendario de las demás competiciones con datos públicos

**Estado:** propuesta para Leo (2026-10-21). No se construye nada con este documento. Contexto: Starter cubre solo la Premier League; Leo
decidió cubrir Champions, Europa League, Conference, FA Cup y Carabao con consultas web programadas de información pública
([decision-draft.md](decision-draft.md), sección «Respuestas de Sportmonks»).

## (a) Qué necesitamos
- **Imprescindible (M3 y capa «Otras competiciones» del Calendario):** fecha y hora de saque, qué club juega, local/visitante y
  aplazamientos/cambios de fecha. Con eso se calculan los días de descanso y el aviso de rotación (`ROTATION_AFTER`: UCL, UEL, UECL, FA, EFL).
- **Deseable, no imprescindible:** alineaciones y minutos en esos partidos, para preguntas de rotación («¿Nunes juega de inicio en los
  partidos grandes de Champions?»). Sin ellos, el aviso por descanso sigue funcionando; las alineaciones no bloquean la primera versión.

## (b) Fuentes candidatas y condiciones
Verificado hoy: los `robots.txt` indicados. **No verificado:** el texto completo de los términos de uso de cada web. Un `robots.txt`
permisivo no es una licencia.

| Necesidad | Fuente | Qué se comprobó | Riesgo |
|---|---|---|---|
| Calendario UCL/UEL/UECL | uefa.com (páginas de partidos; sitemap de partidos publicado) | `robots.txt`: sin regla contra las páginas de competición; sin APIs vetadas. Un resumen de búsqueda de sus términos habla de licencia **personal y no comercial**; la cláusula contra extracción automática **no se pudo confirmar** | **Alto:** leer los términos antes de automatizar; podría prohibir el acceso automatizado |
| Calendario UCL/UEL (alternativa abierta) | openfootball (repo `europe-champions-league`, dominio público/CC0 según su ficha) | No se verificó que el repo tenga la temporada 2026-27 ni horas de saque | Mantenimiento comunitario: retrasos y huecos; los aplazamientos pueden tardar |
| Calendario general (cualquier competición) | Wikipedia (API y páginas) | `robots.txt` permite uso con respeto de límites; texto CC BY-SA | Atribución y compartir igual; tablas con estructura variable; revisiones |
| FA Cup | thefa.com | `robots.txt`: sin regla sobre fixtures/resultados (solo restricciones a agentes concretos) | Términos sin leer |
| Carabao Cup | efl.com | Su `robots.txt` **no se pudo leer** (la web devuelve la aplicación, renderizada con JavaScript) | Probable necesidad de navegador sin cabeza; términos sin leer; **marcar como bloqueado hasta resolverlo** |
| Calendario UCL (API) | football-data.org (plan gratis) | Incluye Champions, **no FA Cup**; ~10 llamadas/min; términos de uso comercial **no confirmados** | Probable restricción comercial; sin copas |
| Alineaciones/minutos (deseable) | páginas de partido de uefa.com / sitios de clubes | Las oficiales salen ~1 h antes del saque (dato de la guía de Sportmonks, no comprobado en estas webs); términos sin leer | Mismo riesgo de términos; sin datos antes de la hora |

Regla propuesta: **ninguna fuente entra en automático sin que Leo haya leído sus términos**; si alguna prohíbe el acceso automatizado, se
descarta o se pide permiso. Esto no es asesoría legal.

## (c) Cadencia, dónde corre y cómo se ve un fallo
- **Calendario completo: semanal.** **Comprobación diaria en semanas con partido** (aplazamientos y cambios de hora), más una pasada el
  día del partido.
- **Dónde:** **GitHub Actions con `cron`**, como `publish-stats.yml` (diario 05:00 UTC). **No** el Programador de tareas de Windows. Sin
  secretos. Como `main` está protegida, el resultado viaja como PR de un bot (el mismo patrón y la misma salvedad del token que
  `publish-stats.yml`).
- **Cómo se hace visible un fallo:** (1) el job abre/actualiza una issue de alerta al fallar y la cierra al tener éxito (patrón de
  `publish-stats.yml`); (2) el archivo lleva sello «actualizado el …» por competición y la tabla avisa en pantalla cuando pasa de N días.
  Un fallo silencioso es el riesgo principal.

## (d) Dónde encaja hoy y primer corte mínimo
Hoy: `football_intelligence.live_trial_calendar.build_calendar` (entrada: captura del trial, solo desarrollo) →
`fpl_grounded_assistant.competition_calendar.competitions_response` (`GET /fixtures/competitions`, por nivel) → ruta
`fpl-fixture-competitions` de `fpl-ui` → `FixtureCompetitionExtras`. En producción responde `available: false` (no hay origen de datos
público). El calendario de la Premier League sigue viniendo de FPL.
**Primer corte mínimo:** un normalizador puro que convierta **una competición (Champions) desde una sola fuente** a la misma lista
de partidos por club que ya consume `competition_calendar`, con el sello de actualización y comprobación de nombres de club contra los
códigos de 3 letras; sin cron todavía y sin tocar la interfaz. Después: cron semanal, luego la pasada diaria, luego Europa/Conference,
luego las copas.

## (e) Riesgos y degradación
- **Cambio de la fuente** (HTML o términos): el normalizador falla de forma visible, no devuelve datos a medias.
- **Dato ausente ≠ «sin partido»:** si falta una competición o está desactualizada, la capa se omite o se marca; **el aviso de rotación
  no se emite** sobre un calendario incompleto (el riesgo R6 de aplazamientos invisibles se agrava).
- **Nombres de club** entre fuentes (ya hay casos en `SHORT_CODE_DISPLAY`): cualquier club sin código seguro se muestra sin aviso.
- **Términos:** una fuente cuya licencia no permita acceso automatizado se descarta.
- **Regla general:** degradar con gracia (la capa de «Otras competiciones» desaparece, el resto del Calendario no cambia).
