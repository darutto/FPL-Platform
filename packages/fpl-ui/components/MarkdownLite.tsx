import React from 'react';

/** Inline `**bold**` → <strong>; everything else stays plain text. */
function renderInline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i} className="font-bold text-white">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
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

/**
 * Dependency-free minimal markdown: paragraphs, headings (`#`–`######`),
 * bullet lists (`* ` / `- `), numbered lists (`1. ` / `1) `) and inline
 * `**bold**`. NOT a full markdown parser — deliberately tiny so the app never
 * surfaces raw `###` / `1.` / asterisks (or a monospace wall of text) in place
 * of structure. Shared by the chat text bubble, the multi-intent child text,
 * and the web-search cards so all four render identically.
 *
 * Out of scope, on purpose: nested lists, code blocks, tables, links. Those
 * render as plain paragraphs/items.
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

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushList();
      continue;
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
