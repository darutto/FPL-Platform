/**
 * CommandIcons — SVG icon set for the quick-commands panel (Stitch Hi-Fi).
 *
 * Ported 1:1 from the design prototype. Each icon takes its accent color as
 * a prop (values come from lib/theme ACCENT_HEX — never hardcoded here).
 * Decorative: parent rows carry the accessible labels.
 */

interface IconProps {
  color: string;
}

export const IconCaptain = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <circle cx="11" cy="11" r="10" stroke={color} strokeWidth="1.5" />
    <path d="M11 5l1.5 4.5H17l-3.75 2.7 1.43 4.4L11 14l-3.68 2.6 1.43-4.4L5 9.5h4.5z" fill={color} opacity=".9" />
  </svg>
);

export const IconCompare = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <rect x="3" y="4" width="7" height="14" rx="2" stroke={color} strokeWidth="1.5" />
    <rect x="12" y="4" width="7" height="14" rx="2" stroke={color} strokeWidth="1.5" opacity=".55" />
    <path d="M9 11h4M11 9l2 2-2 2" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" opacity=".8" />
  </svg>
);

export const IconTransfer = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <path d="M5 8h12M14 5l3 3-3 3" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M17 14H5M8 11l-3 3 3 3" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconFixtures = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <rect x="3" y="5" width="16" height="14" rx="2" stroke={color} strokeWidth="1.5" />
    <path d="M3 9h16" stroke={color} strokeWidth="1.5" />
    <path d="M7 3v4M15 3v4" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <rect x="6" y="12" width="3" height="3" rx=".5" fill={color} opacity=".7" />
    <rect x="10" y="12" width="3" height="3" rx=".5" fill={color} opacity=".5" />
    <rect x="14" y="12" width="3" height="3" rx=".5" fill={color} opacity=".3" />
  </svg>
);

export const IconDiff = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <circle cx="11" cy="11" r="4" stroke={color} strokeWidth="1.5" />
    <circle cx="11" cy="11" r="8" stroke={color} strokeWidth="1" opacity=".4" strokeDasharray="3 2" />
    <path d="M11 4V2M11 20v-2M4 11H2M20 11h-2" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

export const IconChip = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <circle cx="11" cy="11" r="9" stroke={color} strokeWidth="1.5" />
    <circle cx="11" cy="11" r="6.5" stroke={color} strokeWidth="1" strokeDasharray="2.5 1.8" opacity=".6" />
    <circle cx="11" cy="11" r="3.5" fill={color} opacity=".25" stroke={color} strokeWidth="1.2" />
    <path
      d="M11 2v2M11 18v2M2 11h2M18 11h2M4.22 4.22l1.41 1.41M16.37 16.37l1.41 1.41M4.22 17.78l1.41-1.41M16.37 5.63l1.41-1.41"
      stroke={color}
      strokeWidth="1.3"
      strokeLinecap="round"
    />
  </svg>
);

export const IconRanking = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <rect x="3" y="13" width="4" height="6" rx="1" stroke={color} strokeWidth="1.5" />
    <rect x="9" y="8" width="4" height="11" rx="1" stroke={color} strokeWidth="1.5" fill={color} fillOpacity=".12" />
    <rect x="15" y="11" width="4" height="8" rx="1" stroke={color} strokeWidth="1.5" />
    <path d="M11 5l.8 1.6 1.7.2-1.2 1.2.3 1.7-1.6-.9-1.6.9.3-1.7L9.5 6.8l1.7-.2z" fill={color} />
  </svg>
);

export const IconInjury = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <rect x="3" y="3" width="16" height="16" rx="3" stroke={color} strokeWidth="1.5" />
    <path d="M11 7v8M7 11h8" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
);

export const IconForm = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <path d="M12 2L4 13h6l-1 7 8-11h-6l1-7z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill={color} fillOpacity=".15" />
  </svg>
);

export const IconXG = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <circle cx="11" cy="11" r="8" stroke={color} strokeWidth="1.5" />
    <circle cx="11" cy="11" r="4" stroke={color} strokeWidth="1.5" />
    <circle cx="11" cy="11" r="1.4" fill={color} />
    <path d="M11 1v2M11 19v2M1 11h2M19 11h2" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

export const IconPoints = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <path d="M6 3h10v6a5 5 0 0 1-10 0V3z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M6 5H3v2a3 3 0 0 0 3 3M16 5h3v2a3 3 0 0 1-3 3" stroke={color} strokeWidth="1.3" />
    <path d="M9 19h4M11 14v5" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

export const IconMinutes = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <circle cx="11" cy="11" r="8" stroke={color} strokeWidth="1.5" />
    <path d="M11 6v5l3.5 2.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconPopular = ({ color }: IconProps) => (
  <svg aria-hidden="true" width="20" height="20" viewBox="0 0 22 22" fill="none">
    <path d="M3 16l3-10 5 6 5-6 3 10H3z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill={color} fillOpacity=".08" />
    <circle cx="11" cy="4" r="1.4" fill={color} />
    <circle cx="3.5" cy="6.5" r="1.2" fill={color} />
    <circle cx="18.5" cy="6.5" r="1.2" fill={color} />
  </svg>
);
