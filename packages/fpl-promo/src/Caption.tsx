import { useCurrentFrame } from 'remotion';
import { p } from './anim';
import { C, F } from './theme';

interface Props {
  text: string;
  /** Frame the first word starts sliding in. */
  start: number;
  /** Frame the line starts sliding out (upwards). */
  end: number;
  y?: number;
  size?: number;
  /** Words to colour turquoise. */
  accent?: string[];
}

const PER_WORD = 4;

/** Word-by-word slide-up in place, clipped by a mask: no bounce, no letter fades. */
export const Caption: React.FC<Props> = ({ text, start, end, y = 330, size = 64, accent = [] }) => {
  const frame = useCurrentFrame();
  if (frame < start - 1 || frame > end + 14) return null;
  const words = text.split(' ');
  const out = p(frame, end, 12);
  return (
    <div
      style={{
        position: 'absolute',
        top: y,
        left: 70,
        right: 70,
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        columnGap: size * 0.28,
        rowGap: size * 0.05,
        fontFamily: F.sans,
        fontWeight: 800,
        fontSize: size,
        lineHeight: 1.12,
        letterSpacing: -0.5,
        color: C.text,
        textAlign: 'center',
      }}
    >
      {words.map((w, i) => {
        const inP = p(frame, start + i * PER_WORD, 10);
        const ty = (1 - inP) * 110 - out * 110;
        const clean = w.replace(/[¿?¡!.,…]/g, '');
        return (
          <span key={i} style={{ display: 'inline-block', overflow: 'hidden', paddingBottom: 6 }}>
            <span
              style={{
                display: 'inline-block',
                transform: `translateY(${ty}%)`,
                color: accent.includes(clean) ? C.turquoise : undefined,
              }}
            >
              {w}
            </span>
          </span>
        );
      })}
    </div>
  );
};
