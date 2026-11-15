/* One small stroke-icon set (24x24, currentColor). Inline SVG so the strict Content-Security-Policy needs no exceptions. */
const P: Record<string, string> = {
  home: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  queue: 'M4 6h3M4 12h3M4 18h3M10 6h10M10 12h10M10 18h10',
  chat: 'M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z',
  users: 'M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7M21 19v-1a4 4 0 00-3-3.9M15.5 3.2a3.5 3.5 0 010 6.6',
  bolt: 'M13 2L4 14h7l-1 8 9-12h-7l1-8z',
  plug: 'M9 2v6M15 2v6M6 8h12v3a6 6 0 01-12 0V8zM12 17v5',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16z',
  book: 'M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5zM4 19a2 2 0 012-2h13',
  cog: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.9 2.9l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-2.9-1.2l-.1.1a2 2 0 11-2.9-2.9l.1-.1A1.7 1.7 0 003 14H3a2 2 0 010-4h.1A1.7 1.7 0 004.6 7l-.1-.1a2 2 0 112.9-2.9l.1.1A1.7 1.7 0 0010 3.1V3a2 2 0 014 0v.1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.9 2.9l-.1.1a1.7 1.7 0 00-.3 1.8 1.7 1.7 0 001.5 1H21a2 2 0 010 4h-.1a1.7 1.7 0 00-1.5 1z',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2',
  mail: 'M3 6h18v12H3zM3 7l9 6 9-6',
  alert: 'M12 3l10 17H2L12 3zM12 10v4M12 17.5v.5',
  check: 'M4 12l5 5L20 6',
  invoice: 'M6 2h9l4 4v16l-3-2-2 2-2-2-2 2-2-2-2 2V2zM9 9h6M9 13h6',
  doc: 'M6 2h8l5 5v15H6zM14 2v5h5M9 13h6M9 17h6',
  snow: 'M12 2v20M4 6l16 12M20 6L4 18',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  reply: 'M9 14L4 9l5-5M4 9h9a7 7 0 017 7v4',
  phone: 'M5 3h4l2 5-2.5 1.5a11 11 0 005 5L15 12l5 2v4a2 2 0 01-2 2A16 16 0 013 5a2 2 0 012-2z',
  trophy: 'M8 4h8v5a4 4 0 01-8 0V4zM8 6H4a3 3 0 003 4M16 6h4a3 3 0 01-3 4M12 13v5M8 21h8',
  arrow: 'M5 12h14M13 6l6 6-6 6',
};
export type IconName = keyof typeof P;
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[name] ?? P.arrow} /></svg>;
}
/** Icon on a tinted tile; `tone` picks the colour token. */
export function IconTile({ name, tone = 'fern', size = 38 }: { name: string; tone?: 'fern' | 'amber' | 'bad' | 's1' | 's3' | 's4' | 'muted'; size?: number }) {
  return <span className="itile" style={{ ['--t' as string]: `var(--${tone})`, width: size, height: size }}><Icon name={name} size={Math.round(size * 0.5)} /></span>;
}
