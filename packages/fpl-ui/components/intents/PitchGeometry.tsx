/**
 * PitchGeometry — the penalty-box drawing shared by the zone views.
 *
 * Extracted verbatim from DefensiveZonesCard (i152) so the opponent-weakness
 * card and the player «Zonas» mini-pitch draw the same box. SVG user units
 * (viewBox 0 0 360 210 for the box alone): the attacker faces the goal at the
 * top, attacker's left = viewer's left.
 *
 * DefensiveZonesCard's markup is pinned by
 * __tests__/defensive-zones-markup.test.tsx (snapshot recorded before the
 * extraction): do not change an attribute here without re-reading that test.
 */

/** Penalty-box thirds in SVG units: x origin per zone, region width/bounds. */
export const ZONE_X = [30, 130, 230];
export const ZONE_WIDTH = 100;
export const ZONE_CENTER_X = [80, 180, 280];

/** Box outline, six-yard box, goal, thirds guides, spot and arc — no fills. */
export function PitchLines() {
  return (
    <>
      <rect x="30" y="26" width="300" height="150" fill="none" stroke="rgba(255,255,255,.18)" strokeWidth="1.5" />
      <rect x="110" y="26" width="140" height="46" fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="1.5" />
      <rect x="150" y="20" width="60" height="6" fill="rgba(255,255,255,.85)" />
      <line x1="130" y1="26" x2="130" y2="176" stroke="rgba(255,255,255,.08)" strokeWidth="1" strokeDasharray="4 5" />
      <line x1="230" y1="26" x2="230" y2="176" stroke="rgba(255,255,255,.08)" strokeWidth="1" strokeDasharray="4 5" />
      <circle cx="180" cy="112" r="3" fill="rgba(255,255,255,.4)" />
      <path d="M 140 176 A 45 45 0 0 0 220 176" fill="none" stroke="rgba(255,255,255,.12)" strokeWidth="1.5" />
    </>
  );
}
