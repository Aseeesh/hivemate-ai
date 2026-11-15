'use client';
import { useEffect, useRef, useState, type ReactNode } from 'react';

/* Plain SVG/CSS charts: no dependency, theme colours from CSS variables (see globals.css), motion off under prefers-reduced-motion. */

const reduced = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function CountUp({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const [v, setV] = useState(reduced() ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced()) { setV(value); return; }
    const start = performance.now(), a = from.current, dur = 800; let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 3);
      setV(a + (value - a) * e);
      if (k < 1) raf = requestAnimationFrame(tick); else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{v.toFixed(decimals)}</>;
}

const dayLabel = (d: string) => new Date(d + 'T00:00:00Z').toLocaleDateString('en-NZ', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** One measure per day as bars. Hover (or focus) a bar for the exact number; a table view is one click away. */
export function DayBars({ title, data, color = 'var(--s1)', unit }: { title: string; data: { day: string; v: number }[]; color?: string; unit: string }) {
  const [hot, setHot] = useState<number | null>(null);
  const W = 340, H = 130, pad = 20, bw = (W - pad) / data.length, max = Math.max(1, ...data.map((d) => d.v));
  const total = data.reduce((s, d) => s + d.v, 0);
  return (
    <figure className="card viz" aria-label={title}>
      <figcaption className="row" style={{ justifyContent: 'space-between' }}><strong>{title}</strong><span className="muted">{total} in {data.length} days</span></figcaption>
      <div style={{ position: 'relative' }}>
        <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label={`${title}: ${data.map((d) => `${dayLabel(d.day)} ${d.v}`).join(', ')}`} style={{ width: '100%', height: 'auto' }}>
          {[0.5, 1].map((f) => <line key={f} x1={pad} x2={W} y1={H - f * (H - 14)} y2={H - f * (H - 14)} stroke="var(--line)" strokeWidth="1" />)}
          <text x="0" y={H - (H - 14) + 4} fontSize="9" fill="var(--muted)">{max}</text>
          {data.map((d, i) => {
            const h = Math.max(d.v ? 3 : 0, (d.v / max) * (H - 14)), x = pad + i * bw + 2;
            return (
              <g key={d.day} onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} onFocus={() => setHot(i)} onBlur={() => setHot(null)} tabIndex={0} aria-label={`${dayLabel(d.day)}: ${d.v} ${unit}`}>
                <rect x={pad + i * bw} y={0} width={bw} height={H} fill="transparent" />
                <rect className="bar-grow" x={x} y={H - h} width={Math.max(2, bw - 4)} height={h} rx="3" fill={color} opacity={hot === null || hot === i ? 1 : 0.45} style={{ animationDelay: `${i * 35}ms` }} />
              </g>
            );
          })}
          <text x={pad} y={H + 14} fontSize="10" fill="var(--muted)">{dayLabel(data[0].day)}</text>
          <text x={W} y={H + 14} fontSize="10" fill="var(--muted)" textAnchor="end">{dayLabel(data[data.length - 1].day)}</text>
        </svg>
        {hot !== null && <div className="tip" style={{ left: `${((pad + hot * bw + bw / 2) / W) * 100}%` }}>{dayLabel(data[hot].day)}<br /><b>{data[hot].v}</b> {unit}</div>}
      </div>
      <details><summary className="muted" style={{ cursor: 'pointer' }}>View as table</summary>
        <table><thead><tr><th>Day</th><th>{unit}</th></tr></thead><tbody>{data.map((d) => <tr key={d.day}><td>{dayLabel(d.day)}</td><td>{d.v}</td></tr>)}</tbody></table>
      </details>
    </figure>
  );
}

/** Parts of a whole as one stacked bar with a legend that carries the numbers. */
export function Segments({ title, parts, empty }: { title: string; parts: { label: string; value: number; color: string }[]; empty: string }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  return (
    <figure className="card viz" aria-label={title}>
      <figcaption><strong>{title}</strong></figcaption>
      {total === 0 ? <p className="muted">{empty}</p> : <>
        <div className="seg" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(', ')}>
          {parts.filter((p) => p.value > 0).map((p, i) => <span key={p.label} className="seg-fill" style={{ flexGrow: p.value, background: p.color, animationDelay: `${i * 120}ms` }} title={`${p.label}: ${p.value}`} />)}
        </div>
        <ul className="legend">{parts.map((p) => <li key={p.label}><i style={{ background: p.color }} />{p.label} <b>{p.value}</b> <span className="muted">({Math.round((p.value / total) * 100)}%)</span></li>)}</ul>
      </>}
    </figure>
  );
}

/** Ranked horizontal bars (one measure, many items). */
export function RankBars({ title, rows, unit, onPick }: { title: string; rows: { id: string; label: string; value: number }[]; unit: string; onPick?: (id: string) => void }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <figure className="card viz" aria-label={title}>
      <figcaption><strong>{title}</strong></figcaption>
      <div className="rank">
        {rows.map((r, i): ReactNode => (
          <button key={r.id} className="rank-row" onClick={() => onPick?.(r.id)} aria-label={`${r.label}: ${r.value} ${unit}`}>
            <span className="rank-name">{r.label}</span>
            <span className="rank-track"><span className="rank-fill" style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${i * 60}ms` }} /></span>
            <b>{r.value}</b>
          </button>
        ))}
        {!rows.length && <p className="muted">Nothing yet.</p>}
      </div>
    </figure>
  );
}

/** A percentage as a ring. `null` renders an empty ring with "no data", never a made-up number. */
export function Ring({ value, label, sub, color = 'var(--fern)', size = 112 }: { value: number | null; label: string; sub?: string; color?: string; size?: number }) {
  const r = 42, c = 2 * Math.PI * r, v = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <figure className="ring" aria-label={`${label}: ${value == null ? 'no data yet' : `${value}%`}`}>
      <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-hidden="true">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--track)" strokeWidth="9" />
        {v > 0 && <circle className="ring-arc" cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round" strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 50 50)" />}
        <text x="50" y="50" textAnchor="middle" dominantBaseline="central" fontSize={value == null ? 11 : 22} fontWeight="650" fill="var(--ink)">{value == null ? 'no data' : `${value}%`}</text>
      </svg>
      <figcaption><strong>{label}</strong>{sub && <span className="muted">{sub}</span>}</figcaption>
    </figure>
  );
}

/** Tiny trend line with a soft area and an emphasised last point. */
export function Spark({ data, color = 'var(--fern)', width = 120, height = 36 }: { data: number[]; color?: string; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const max = Math.max(1, ...data), step = width / (data.length - 1);
  const pts = data.map((d, i) => [i * step, height - 4 - (d / max) * (height - 8)] as const);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden="true" style={{ display: 'block', overflow: 'visible' }}>
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={color} opacity=".14" />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r="3" fill={color} />
    </svg>
  );
}

/** Stages of the enquiry pipeline as bars that narrow, each clickable. Widths are proportional to the largest stage. */
export function Funnel({ stages, onPick }: { stages: { id: string; label: string; value: number; color: string }[]; onPick?: (id: string) => void }) {
  const max = Math.max(1, ...stages.map((s) => s.value));
  return (
    <div className="funnel" role="list">
      {stages.map((s, i) => (
        <button key={s.id} role="listitem" className="funnel-row" onClick={() => onPick?.(s.id)} aria-label={`${s.label}: ${s.value}`}>
          <span className="funnel-label">{s.label}</span>
          <span className="funnel-track"><span className="funnel-fill" style={{ width: `${Math.max(s.value ? 6 : 0, (s.value / max) * 100)}%`, background: s.color, animationDelay: `${i * 70}ms` }} /></span>
          <b>{s.value}</b>
        </button>
      ))}
    </div>
  );
}
