/**
 * Finds the Spanish literals the UI source still carries outside the dictionary (lib/i18n).
 *
 * It reads TypeScript syntax, not text: string literals, template literal pieces and JSX text, so comments and
 * identifiers never count. A literal is "Spanish" when it has a Spanish letter or mark (á é í ó ú ñ ¿ ¡), uses two or
 * more Spanish function words, or uses one word that only Spanish has. That is a heuristic on purpose: it catches the
 * Spanish this UI actually writes, it does not claim to detect every Spanish sentence, and it never reads the
 * dictionary (that is where Spanish belongs).
 */
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

/** Directories scanned, relative to the package root. */
export const SCANNED = ['app', 'components', 'lib'];
/** Never scanned: the dictionary itself, committed data, tests. */
const SKIPPED = [/^lib[\\/]i18n[\\/]/, /^lib[\\/]data[\\/]/, /\.test\.tsx?$/, /\.d\.ts$/];

const FUNCTION_WORDS = new Set(
  'de del la las los el un una por para con sin que se su sus tu mi hay muy al como desde hasta sobre entre cuando donde esta este estos estas ya todos todas nuevo nueva lo le les'.split(
    ' ',
  ),
);
const ONLY_SPANISH = new Set(
  'jornada jornadas partido partidos jugador jugadores equipo equipos temporada plantilla reintentar cargando detalle ajuste zona zonas visitante ataque defensiva ofensiva racha calendario lesionados gratis hoy forma banco suscribirte suscripcion cerrar iniciar sesion'.split(
    ' ',
  ),
);

export function normalise(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

export function isSpanish(raw: string): boolean {
  const text = normalise(raw);
  if (text.length < 2) return false;
  // identifiers and paths (test ids, locale tags, routes): player-zonas-chips, es-ES, /api/fpl-squad
  if (/^[\w]+([-_./:][\w]+)+$/.test(text)) return false;
  if (/[áéíóúñ¿¡ÁÉÍÓÚÑ]/.test(text)) return true;
  const words = text.toLowerCase().match(/[a-z]{2,}/g) ?? [];
  if (words.some((w) => ONLY_SPANISH.has(w))) return true;
  return words.filter((w) => FUNCTION_WORDS.has(w)).length >= 2;
}

function sourceFiles(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(root, full);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (/\.tsx?$/.test(entry.name) && !SKIPPED.some((re) => re.test(rel))) {
        out.push(rel);
      }
    }
  };
  for (const dir of SCANNED) if (fs.existsSync(path.join(root, dir))) walk(path.join(root, dir));
  return out.sort();
}

function literalsOf(source: ts.SourceFile): string[] {
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return; // module paths are not text
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) found.push(node.text);
    else if (ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) found.push(node.text);
    else if (ts.isJsxText(node)) found.push(node.text);
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

/** file (relative, forward slashes) -> the sorted distinct Spanish literals in it. */
export function scanSpanishLiterals(root: string): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  for (const rel of sourceFiles(root)) {
    const text = fs.readFileSync(path.join(root, rel), 'utf8');
    const kind = rel.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
    const source = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, kind);
    const spanish = [...new Set(literalsOf(source).map(normalise).filter(isSpanish))].sort();
    if (spanish.length) result[rel.replace(/\\/g, '/')] = spanish;
  }
  return result;
}
