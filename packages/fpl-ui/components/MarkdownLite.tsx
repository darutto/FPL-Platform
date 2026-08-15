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
 * Dependency-free minimal markdown: paragraphs, bullet lists (`* ` / `- `),
 * and inline `**bold**`. NOT a full markdown parser — deliberately tiny so the
 * app never surfaces raw asterisks/dashes (or a monospace wall of text) in
 * place of structure. Shared by the chat text bubble, the multi-intent child
 * text, and the web-search cards so all four render identically.
 *
 * Sizing and colour are owned by the caller's wrapper; only inline bold pins a
 * colour (`text-white`) as emphasis.
 */
export default function MarkdownLite({ text, className }: Props) {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (bullets.length === 0) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc pl-4 space-y-1">
        {bullets.map((b, i) => (
          <li key={i}>{renderInline(b)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushBullets();
      continue;
    }
    const bullet = line.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
    } else {
      flushBullets();
      blocks.push(
        <p key={`p-${blocks.length}`} className="leading-relaxed">
          {renderInline(line)}
        </p>,
      );
    }
  }
  flushBullets();

  return <div className={className ? `space-y-2 ${className}` : 'space-y-2'}>{blocks}</div>;
}
