/**
 * What is on screen, as plain strings, for the language tests.
 *
 * The text of an element is its own text nodes joined, so how JSX happens to split a sentence into nodes
 * ("J" + "7" or "J7") does not show. Titles and aria-labels are included: they are read by people too.
 */

/** Every distinct text, plus every title and aria-label, under `root`. */
export function onScreen(root: HTMLElement): string[] {
  const out = new Set<string>();
  const elements = [root, ...Array.from(root.querySelectorAll('*'))];
  for (const el of elements) {
    const own = Array.from(el.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent ?? '')
      .join('')
      .replace(/\s+/g, ' ')
      .trim();
    if (own) out.add(own);
    for (const attr of ['title', 'aria-label']) {
      const v = el.getAttribute(attr);
      if (v) out.add(`[${attr}] ${v}`);
    }
  }
  return [...out];
}

/** The same with numbers and three-letter club codes folded, sorted: the shape of the screen, stable across the season. */
export function shape(root: HTMLElement): string[] {
  return [
    ...new Set(
      onScreen(root).map((s) =>
        s.replace(/\b(?!FDR\b|xGA\b)[A-Z]{3}\b/g, 'XXX').replace(/\d+(\.\d+)?/g, 'N'),
      ),
    ),
  ].sort();
}

/** Spanish interface words that must not survive in an English screen. */
export const SPANISH_UI_WORDS =
  /\b(jornadas?|ataque|ataca|porter[ií]a|izquierda|derecha|centro|jugador|zona|ajuste|ventaja|partidos?|equipo|plantilla|temporada|cargando|reintentar|detalle|capit[aá]n|forma|banco|rival|rivales|cruce|favorable|muestra|corta|jugada|bal[oó]n|parado|tiros?|visita|recibe|dentro|frontal|[aá]rea|media|penaltis|excluidos|conecta|pesta[nñ]a|cu[eé]ntame|mientras|revisa|calendario|pregunta)\b/i;
