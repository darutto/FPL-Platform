import React from 'react';

/**
 * i126: `*italic*` — an asterisk that opens on a non-space and closes on a
 * non-space, with no asterisk inside. So "5 * 2" and "a * b * c" stay literal,
 * and a `**` pair never reads as two italics (bold is split out first).
 * `_italic_` is deliberately NOT supported: underscores live inside names
 * (`dgw_teams`, `web_name`) and would turn them into italics. No lookbehind:
 * older Safari throws on it at parse time, which would take the bundle down.
 */
const ITALIC = /(\*[^\s*](?:[^*]*[^\s*])?\*)/g;

function renderItalics(text: string, keyPrefix: string): React.ReactNode[] {
  return text.split(ITALIC).map((part, i) =>
    i % 2 === 1 ? (
      <em key={`${keyPrefix}-${i}`} className="italic">
        {part.slice(1, -1)}
      </em>
    ) : (
      <span key={`${keyPrefix}-${i}`}>{part}</span>
    ),
  );
}

/** Inline `**bold**` → <strong>, `*italic*` → <em>; everything else stays plain text. */
function renderInline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i} className="font-bold text-white">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <React.Fragment key={i}>{renderItalics(part, String(i))}</React.Fragment>
    ),
  );
}

interface Props {
  text: string;
  /** Extra classes merged onto the wrapper (sizing/colour live on the caller). */
  className?: string;
}

/**
 * Heading classes by `#` depth, capped at three sizes: `#`/`##` share the
 * largest so a model that opens with `# Título` doesn't blow up the bubble;
 * `####`+ collapse into the smallest.
 */
const HEADING_CLASS: Record<number, string> = {
  1: 'text-base font-bold text-white leading-snug',
  2: 'text-base font-bold text-white leading-snug',
  3: 'text-[15px] font-semibold text-white leading-snug',
  4: 'text-sm font-semibold text-white leading-snug',
  5: 'text-sm font-semibold text-white leading-snug',
  6: 'text-sm font-semibold text-white leading-snug',
};

type ListKind = 'ul' | 'ol';

type Align = 'left' | 'center' | 'right' | undefined;

/**
 * i138: split one table row into cells. Leading/trailing pipes are optional
 * (GFM); `\|` is a literal pipe inside a cell, not a column break.
 */
function splitRow(line: string): string[] {
  let body = line.trim();
  if (body.startsWith('|')) body = body.slice(1);
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1);
  const cells: string[] = [];
  let cell = '';
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === '\\' && body[i + 1] === '|') {
      cell += '|';
      i++;
    } else if (ch === '|') {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += ch;
    }
  }
  cells.push(cell.trim());
  return cells;
}

/** A GFM separator cell: dashes with optional alignment colons (`:--`, `--:`, `:-:`). */
const SEPARATOR_CELL = /^:?-+:?$/;

/**
 * i138: the alignments of a separator row, or null when `line` is not one.
 * It must have exactly `columns` cells, so a stray `---` (or a row of dashes
 * of another width) never turns the line above it into a table header.
 */
function parseSeparator(line: string, columns: number): Align[] | null {
  if (!line.includes('-')) return null;
  const cells = splitRow(line);
  if (cells.length !== columns || !cells.every((c) => SEPARATOR_CELL.test(c))) return null;
  return cells.map((c) => {
    const left = c.startsWith(':');
    const right = c.endsWith(':');
    if (left && right) return 'center';
    if (right) return 'right';
    if (left) return 'left';
    return undefined;
  });
}

/**
 * Dependency-free minimal markdown: paragraphs, headings (`#`–`######`),
 * bullet lists (`* ` / `- `), numbered lists (`1. ` / `1) `), inline
 * `**bold**` and inline `*italic*`. NOT a full markdown parser — deliberately tiny so the app never
 * surfaces raw `###` / `1.` / asterisks (or a monospace wall of text) in place
 * of structure. Shared by the chat text bubble, the multi-intent child text,
 * and the web-search cards so all four render identically.
 *
 * i138: GFM tables -- a header row, a separator row of the same width
 * (`---`, alignment `:--` / `--:` / `:-:`), then rows until a blank line or a
 * line without `|`. A line with a stray `|` and no separator below stays a
 * paragraph. The table scrolls horizontally inside its own wrapper, so a wide
 * comparison never widens the bubble on mobile.
 *
 * Out of scope, on purpose: nested lists, code blocks, links. Those render as
 * plain paragraphs/items.
 *
 * Block model: one open list buffer at a time, typed `ul` or `ol`. Any change
 * of block type (bullet→number, list→heading, list→paragraph, blank line)
 * closes the open buffer — so `- a` followed by `1. b` yields one <ul> and one
 * <ol>, never a merged list.
 *
 * Sizing and colour are owned by the caller's wrapper; only inline bold and
 * headings pin `text-white` as emphasis.
 */
export default function MarkdownLite({ text, className }: Props) {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let listKind: ListKind | null = null;
  let items: string[] = [];
  let olStart = 1;

  const flushList = () => {
    if (listKind === null || items.length === 0) {
      listKind = null;
      items = [];
      return;
    }
    const key = `${listKind}-${blocks.length}`;
    const lis = items.map((b, i) => <li key={i}>{renderInline(b)}</li>);
    blocks.push(
      listKind === 'ul' ? (
        <ul key={key} className="list-disc pl-4 space-y-1">
          {lis}
        </ul>
      ) : (
        <ol
          key={key}
          className="list-decimal pl-5 space-y-1"
          start={olStart !== 1 ? olStart : undefined}
        >
          {lis}
        </ol>
      ),
    );
    listKind = null;
    items = [];
  };

  const pushItem = (kind: ListKind, item: string, start?: number) => {
    if (listKind !== kind) {
      flushList();
      listKind = kind;
      olStart = start ?? 1;
    }
    items.push(item);
  };

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li].trim();
    if (!line) {
      flushList();
      continue;
    }
    if (line.includes('|') && li + 1 < lines.length) {
      const header = splitRow(line);
      const aligns = parseSeparator(lines[li + 1].trim(), header.length);
      if (aligns !== null) {
        flushList();
        const rows: string[][] = [];
        li += 2;
        while (li < lines.length && lines[li].trim() && lines[li].includes('|')) {
          const cells = splitRow(lines[li]);
          rows.push(header.map((_, c) => cells[c] ?? ''));
          li++;
        }
        li--; // the for-loop's increment moves past the last row consumed
        const key = `t-${blocks.length}`;
        blocks.push(
          // The one-column minmax(0,1fr) grid gives the table a min-content
          // width of 0: the chat bubble is a flex item whose min-width:auto
          // would otherwise grow to the no-wrap table and push it off-screen
          // on mobile (measured in the i138 capture). It still offers its full
          // width as max-content, so the bubble widens up to its cap and the
          // table scrolls inside.
          <div key={key} className="grid grid-cols-[minmax(0,1fr)]">
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Tabla">
            <table className="border-collapse text-[13px]">
              <thead>
                <tr>
                  {header.map((h, c) => (
                    <th
                      key={c}
                      style={{ textAlign: aligns[c] ?? 'left' }}
                      className="px-2 py-1 font-semibold text-white whitespace-nowrap border-b border-white/20"
                    >
                      {renderInline(h)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td
                        key={c}
                        style={{ textAlign: aligns[c] ?? 'left' }}
                        className="px-2 py-1 whitespace-nowrap border-b border-white/5"
                      >
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </div>,
        );
        continue;
      }
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const depth = heading[1].length;
      const Tag = `h${depth}` as keyof React.JSX.IntrinsicElements;
      blocks.push(
        <Tag key={`h-${blocks.length}`} className={HEADING_CLASS[depth]}>
          {renderInline(heading[2])}
        </Tag>,
      );
      continue;
    }
    const bullet = line.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      pushItem('ul', bullet[1]);
      continue;
    }
    const numbered = line.match(/^(\d+)[.)]\s+(.*)$/);
    if (numbered) {
      pushItem('ol', numbered[2], parseInt(numbered[1], 10));
      continue;
    }
    flushList();
    blocks.push(
      <p key={`p-${blocks.length}`} className="leading-relaxed">
        {renderInline(line)}
      </p>,
    );
  }
  flushList();

  return <div className={className ? `space-y-2 ${className}` : 'space-y-2'}>{blocks}</div>;
}
