import { useState } from "react";
import { Link } from "react-router-dom";
import type { ApiError, AttentionStatus, Category, Freshness, Story } from "../api";
import { fmtDate, fmtDateTime } from "../format";

export const Logo = ({ size = 28 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
    <rect x="3" y="19" width="7" height="9" fill="#ecebe4" /><rect x="12.5" y="12" width="7" height="16" fill="#ecebe4" /><rect x="22" y="5" width="7" height="23" fill="#c6f432" />
  </svg>
);

const CAT: Record<Category, { label: string; cls: string }> = {
  "B+F": { label: "Resource story + attention gap", cls: "bf" },
  B: { label: "Resource story", cls: "b" },
  F: { label: "Attention-gap story", cls: "f" },
};
export const CategoryBadge = ({ c }: { c: Category | null }) =>
  c ? <span className={`badge ${CAT[c].cls}`} title={`Internal code: ${c}`}>{CAT[c].label}</span> : <span className="badge">Unclassified</span>;

const ATT: Record<AttentionStatus, { label: string; cls: string }> = {
  gap_found: { label: "Low Reddit discussion found", cls: "f" },
  discussion_found: { label: "Reddit discussion found", cls: "info" },
  unknown: { label: "Attention check incomplete", cls: "warn" },
};
export const AttentionBadge = ({ s }: { s: AttentionStatus }) => <span className={`badge ${ATT[s].cls}`}>{ATT[s].label}</span>;

export const Skeletons = ({ n = 6 }: { n?: number }) => (
  <div className="grid" aria-busy="true" aria-label="Loading">{Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" />)}</div>
);

export function ErrorBox({ error, retry }: { error: ApiError; retry: () => void }) {
  return (
    <div className="notice err" role="alert">
      <b className="ui">{error.status === 404 ? "No data yet" : "Something went wrong"}</b>
      <p style={{ margin: ".4rem 0 .8rem" }}>{error.message}</p>
      <button className="btn small" onClick={retry}>Try again</button>
    </div>
  );
}

export function FreshnessBanner({ f }: { f: Freshness }) {
  return (
    <>
      {f.is_demo && <div className="banner demo" role="status">Demo data: fictional placeholder stories for previewing the interface. Not real reporting.</div>}
      {!f.is_demo && f.is_stale && (
        <div className="banner stale" role="status">
          Data may be out of date{f.generated_at ? `: last pipeline run ${fmtDateTime(f.generated_at)}` : ""}. Re-run the pipeline for fresh results.
        </div>
      )}
    </>
  );
}

export function StoryCard({ s }: { s: Story }) {
  const who = s.entities.slice(0, 3).join(", ");
  const date = fmtDate(s.published_at);
  return (
    <article className="card">
      <Cover s={s} />
      <div className="row"><CategoryBadge c={s.category} /><AttentionBadge s={s.attention.status} /></div>
      <h3><Link to={`/stories/${s.id}`}>{s.title}</Link></h3>
      <div className="meta">
        {who && <span>{who}</span>}
        {s.source_name && <span>{s.source_name}</span>}
        {date && <time dateTime={s.published_at ?? undefined}>{date}</time>}
      </div>
      {s.description && <p className="small muted" style={{ margin: 0 }}>{s.description.slice(0, 160)}{s.description.length > 160 ? "…" : ""}</p>}
      <div className="foot">
        <span className="meta" title="Ranking score. Not a measure of how good the athlete is.">Rank score {s.scores.combined.toFixed(2)}</span>
        <Link className="btn small" to={`/stories/${s.id}`}>Read story</Link>
      </div>
    </article>
  );
}

const hash = (t: string) => { let h = 2166136261; for (const c of t) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };

/** Cover: the article's own image if the pipeline saved one (credited, hidden on error),
 *  otherwise an original generated podium graphic. Decorative either way. */
export function Cover({ s, tall = false }: { s: Story; tall?: boolean }) {
  const [broken, setBroken] = useState(false);
  const cls = `cover${tall ? " tall" : ""}`;
  if (s.image_url && !broken) {
    return (
      <figure className={cls}>
        <img src={s.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
        {s.source_name && <figcaption>Image: {s.source_name}</figcaption>}
      </figure>
    );
  }
  const h = hash(s.id);
  const n = 7, hi = h % n;
  const bars = Array.from({ length: n }, (_, i) => {
    const hh = 22 + ((h >>> (i * 3)) % 40);
    return { x: 8 + i * 28, h: i === hi ? 78 : hh, lime: i === hi };
  });
  return (
    <div className={cls} aria-hidden="true">
      <svg viewBox="0 0 208 100" preserveAspectRatio="xMidYMax slice" width="100%" height="100%">
        <rect width="208" height="100" fill="#14181d" />
        {bars.map((b, i) => <rect key={i} x={b.x} y={100 - b.h} width="22" height={b.h} fill={b.lime ? "#c6f432" : "#ecebe4"} opacity={b.lime ? 1 : 0.18 + (i % 3) * 0.1} />)}
        <line x1="0" y1="99" x2="208" y2="99" stroke="#ecebe4" strokeWidth="1.5" opacity=".5" />
      </svg>
    </div>
  );
}

export const Unavailable = ({ children = "Not collected" }: { children?: string }) => <span className="muted">{children}</span>;
