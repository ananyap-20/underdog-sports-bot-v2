import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import type { StoryList } from "../api";
import { useApi } from "../hooks";
import { ErrorBox, FreshnessBanner, Skeletons, StoryCard } from "../components/ui";

const KEYS = ["q", "category", "attention", "source", "sort", "page"] as const;

export default function Stories() {
  const [sp, setSp] = useSearchParams();
  const get = (k: string, d = "") => sp.get(k) ?? d;
  const [text, setText] = useState(get("q"));
  // debounce search so we do not call the API on every keystroke
  useEffect(() => {
    const t = setTimeout(() => {
      if (text !== get("q")) update({ q: text, page: "" });
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const update = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  };
  const qs = new URLSearchParams();
  KEYS.forEach((k) => get(k) && qs.set(k, get(k)));
  const { data, error, loading, retry } = useApi<StoryList>(`/api/stories?${qs}`);
  const page = Number(get("page", "1")) || 1;
  const filtered = KEYS.some((k) => k !== "sort" && k !== "page" && get(k));
  const clear = () => { setText(""); setSp({}, { replace: true }); };

  return (
    <>
      {data && <FreshnessBanner f={data.freshness} />}
      <div className="wrap section" style={{ borderTop: 0 }}>
        <h1 style={{ fontSize: "clamp(2.2rem,5vw,3.6rem)" }}>Story explorer</h1>
        <p className="muted" style={{ marginTop: "1rem" }}>Search covers headline, athlete or team, source and description. Sport, event and date filters are not offered because the pipeline does not save those fields.</p>

        <form className="filters" role="search" onSubmit={(e) => e.preventDefault()}>
          <label className="full">Search<input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Athlete, team, headline…" /></label>
          <label>Qualification
            <select value={get("category")} onChange={(e) => update({ category: e.target.value, page: "" })}>
              <option value="">All</option><option value="B+F">Resource story + attention gap</option><option value="B">Resource story</option><option value="F">Attention-gap story</option>
            </select></label>
          <label>Reddit attention check
            <select value={get("attention")} onChange={(e) => update({ attention: e.target.value, page: "" })}>
              <option value="">All</option><option value="gap_found">Low discussion found</option><option value="discussion_found">Discussion found</option><option value="unknown">Check incomplete</option>
            </select></label>
          <label>Source
            <select value={get("source")} onChange={(e) => update({ source: e.target.value, page: "" })}>
              <option value="">All</option>{data?.available_sources.map((s) => <option key={s}>{s}</option>)}
            </select></label>
          <label>Sort by
            <select value={get("sort", "category")} onChange={(e) => update({ sort: e.target.value === "category" ? "" : e.target.value, page: "" })}>
              <option value="category">Pipeline order</option><option value="score">Highest rank score</option><option value="published">Recently published</option><option value="title">Headline A–Z</option>
            </select></label>
          <button type="button" className="btn small" onClick={clear} disabled={!filtered && !text}>Clear</button>
        </form>

        <div aria-live="polite">
          {loading && <Skeletons />}
          {error && <ErrorBox error={error} retry={retry} />}
          {data && data.total === 0 && (
            <div className="notice">{filtered ? "No stories match these filters." : "No qualified stories available yet."} {filtered && <button className="btn small" onClick={clear}>Clear filters</button>}</div>
          )}
          {data && data.total > 0 && (
            <>
              <p className="muted small">{data.total} {data.total === 1 ? "story" : "stories"}. Rank score orders stories; it does not say who is the best athlete.</p>
              <div className="grid">{data.items.map((s) => <StoryCard key={s.id} s={s} />)}</div>
              {data.pages > 1 && (
                <nav className="pager" aria-label="Pagination">
                  <button className="btn small" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>Previous</button>
                  <span>Page {data.page} of {data.pages}</span>
                  <button className="btn small" disabled={page >= data.pages} onClick={() => update({ page: String(page + 1) })}>Next</button>
                </nav>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
