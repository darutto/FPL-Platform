# Base creativa para storyboard (videos 15–30s)

Extraído del código en `main` (nov 2026). Rutas relativas a `packages/fpl-ui/` salvo que se indique.

## 1. Propuesta de valor
- **Qué es:** "FPL Asistente" de Bendito Fantasy (`lib/i18n/es.ts:7-8`). **No es una plataforma de fantasy propia**: no hay draft, puntuación en vivo ni ligas. Es un asistente de IA para tomar decisiones en Fantasy Premier League.
- **Diferenciador:** datos reales de FPL calculados de forma determinista; la IA solo redacta (`README.md`). Explica el porqué (factores del capitán, cruce de zonas, rachas de calendario). En español y hecho por la comunidad del podcast.
- **Cobertura:** Premier League (FPL). Pestaña secundaria "Mundial" (`app/wc/`).
- **Momento de mayor emoción:** la decisión antes del deadline, sobre todo el **capitán** ("¿A quién le doy la cinta?").

## 2. Marca
- **Logo:** solo `public/logo-icon.png` (PNG 1078×1065, RGBA). **No hay SVG ni wordmark** en el repo; hay que pedirlos.
- **Colores** (`tailwind.config.ts`, tokens `bf-*`): bg `#12111a`, surface `#1c1a26`, card `#211F29`, coral `#FF6A4D` (CTA), turquoise `#02EBAE` (positivo/acierto), cyan `#04C4D9`, gold `#F2C572` (top pick), teal `#025E73`, purple `#a78bfa`, gray `#ABA9AC`, text `#f0f0f0`, pitch `#0f3320`.
- **Tipografía:** Barlow (texto) y Archivo Black (cifras grandes) (`app/layout.tsx`).
- **Estilo:** modo oscuro, deportivo y con datos densos. Tarjetas con radio de 12px y sombra suave. Acentos neón coral/turquesa. Pistas de cancha.

## 3. Pantallas heroicas
1. **Squad en el campo**: `components/squad/SquadPitch.tsx`. Tu equipo FPL sobre el césped; tocas un jugador → mini ficha → "Ask AI →".
2. **Zonas (cruce de mapas)**: `components/intents/PlayerZonesPitch.tsx` + `DefensiveZonesCard.tsx`. Porcentaje del xG por zona y "Cruce favorable" en turquesa. Muy visual.
3. **Calendario FDR**: `components/intents/FixturesBoard.tsx` (página `app/fixtures`). Fichas de colores por jornada, rachas y ventanas de 5/8/10, modo "Presentar".
- Extra: `CaptainCard.tsx` (tiers Favorito / Potencial / Diferencial / No esta semana), `ComparisonCard.tsx`, `ShareCard.tsx`.
- Capturas de referencia: `docs/ui/wide-workspace-preview/*.png`.

**Flujo de 3 pasos / 10s:** tocar un jugador en el Squad → "Ask AI →" → respuesta en tarjeta (capitán o zonas).

## 4. Microtextos existentes (`lib/i18n/es.ts`)
- "¿A quién le doy la cinta?" · "Buscar joyas ocultas" · "Baja propiedad, alto potencial"
- "¿Vale la pena el cambio?" · "¿Uso un chip?" · "Los infaltables" · "En racha" · "Peligro de gol"
- "Cuéntame sobre {name} — ¿lo alineo esta semana?" · "Ask AI →" · "Tap a player to see details"
- "Cruce favorable" · "Racha favorable" · "Mejor calendario primero"
- Tiers: "Favorito" · "Potencial" · "Diferencial" · "No esta semana" · "Hipster"
- CTA: "Pruébalo tú también en Club Bendito Fantasy." · "Prueba FPL Asistente gratis con {n} mensajes al día." · "Mejorar en Patreon" · "Unirme"

## Avisos
- Algunos placeholders de la app aún usan Salah / De Bruyne (`es.ts` `slash.comparar.placeholder`, `slash.clasificacion.placeholder`). Que no salgan en pantalla, o corregirlos antes de grabar.
- Hay copys de UI en inglés dentro de la versión ES ("Ask AI →", "Tap a player", "Bench"). Decidir si se unifican antes de grabar.
- No anunciar el XI probable ni los datos de Sportmonks hasta que estén en producción.
