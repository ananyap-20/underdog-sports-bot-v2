import { Link } from "react-router-dom";
import type { Dashboard } from "../api";
import { useApi } from "../hooks";
import { fmtDateTime } from "../format";
import { ErrorBox, FreshnessBanner, Skeletons, StoryCard } from "../components/ui";

const STAGES = [
  ["News discovery", "NewsAPI queries for Indian sports, with a Google News RSS fallback"],
  ["Relevance filter", "Strict Indian-sports check, then de-duplication"],
  ["Enrichment", "Page text and source evidence are attached"],
  ["Story scoring", "spaCy-based achievement and underdog scores"],
  ["Attention check", "Reddit search, with an RSS fallback"],
  ["Qualified stories", "Resource evidence (B) or an attention gap (F)"],
];

function Podium() {
  return (
    <svg viewBox="0 0 240 240" role="img" aria-label="Three podium steps; the lime step on the right is the tallest" style={{ width: "100%", maxWidth: 340, justifySelf: "end" }}>
      <rect x="10" y="150" width="62" height="80" fill="#ecebe4" opacity=".25" /><rect x="88" y="100" width="62" height="130" fill="#ecebe4" opacity=".5" />
      <rect x="166" y="30" width="62" height="200" fill="#c6f432" />
      <line x1="0" y1="230" x2="240" y2="230" stroke="#ecebe4" strokeWidth="2" />
    </svg>
  );
}

export default function Home() {
  const { data, error, loading, retry } = useApi<Dashboard>("/api/dashboard");
  return (
    <>
      {data && <FreshnessBanner f={data.freshness} />}
      <div className="wrap">
        <section className="hero">
          <div>
            <h1>Every champion has a story the world almost missed.</h1>
            <p className="lead">Underdog Sports Bot looks for potentially overlooked Indian sports achievements using news discovery, NLP-assisted scoring and public-attention checks, and shows you the evidence behind every pick.</p>
            <div className="cta-row">
              <Link className="btn primary" to="/stories">Explore stories</Link>
              <Link className="btn" to="/methodology">How it works</Link>
            </div>
            {data?.freshness.generated_at && <p className="small muted" style={{ marginTop: "1rem" }}>Latest pipeline run: {fmtDateTime(data.freshness.generated_at)}</p>}
          </div>
          <Podium />
        </section>

        <section className="section" aria-labelledby="stats-h">
          <h2 id="stats-h">What the last run produced</h2>
          {loading && <Skeletons n={3} />}
          {error && <ErrorBox error={error} retry={retry} />}
          {data && (
            <>
              <div className="stats" style={{ marginTop: "1.5rem" }}>
                <div className="stat"><b>{data.qualified_count}</b><span>Qualified stories</span></div>
                <div className="stat"><b>{data.categories["B+F"]}</b><span>Resource story + attention gap</span></div>
                <div className="stat"><b>{data.categories.B}</b><span>Resource story only</span></div>
                <div className="stat"><b>{data.categories.F}</b><span>Attention-gap story only</span></div>
                <div className="stat"><b>{data.search_days_back ?? "n/a"}</b><span>Days of news searched</span></div>
                <div className="stat"><b>{data.run_count || "n/a"}</b><span>Recorded runs</span></div>
              </div>
              {data.pipeline_funnel ? (
                <div className="bars" style={{ marginTop: "1.5rem" }} aria-label="Pipeline stage counts">
                  {([["articles_scored", "Articles scored"], ["promising_candidates", "Promising candidates"], ["attention_checked", "Attention-checked"], ["qualified", "Qualified"]] as const).map(([k, label]) => {
                    const max = Math.max(1, data.pipeline_funnel?.articles_scored ?? 1);
                    const v = data.pipeline_funnel?.[k] ?? 0;
                    return (
                      <div className="bar" key={k} style={{ gridTemplateColumns: "170px 1fr 56px" }}>
                        <span>{label}</span><i><u style={{ width: `${Math.max(2, (v / max) * 100)}%` }} /></i><span>{v}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="small muted" style={{ marginTop: ".8rem" }}>Stage counts are saved from the next pipeline run onward. This data predates that, so they are not shown rather than guessed.</p>
              )}
            </>
          )}
        </section>

        <section className="section" aria-labelledby="feat-h">
          <h2 id="feat-h">Featured stories</h2>
          <div style={{ marginTop: "1.5rem" }}>
            {loading && <Skeletons n={3} />}
            {data && data.featured.length === 0 && <div className="notice">The last run qualified no stories.</div>}
            {data && <div className="grid">{data.featured.map((s) => <StoryCard key={s.id} s={s} />)}</div>}
          </div>
          <p style={{ marginTop: "1.5rem" }}><Link className="btn" to="/stories">See all stories</Link></p>
        </section>

        <section className="section" aria-labelledby="pipe-h">
          <h2 id="pipe-h">From raw headlines to qualified stories</h2>
          <ol className="steps" style={{ padding: 0 }}>
            {STAGES.map(([t, d]) => <li key={t}>{t}<small>{d}</small></li>)}
          </ol>
          <p className="muted">Discovered, evaluated, rejected and qualified are different counts. Only qualified stories reach this site. <Link to="/methodology">Read the full method and its limits.</Link></p>
        </section>

        <section className="section" aria-labelledby="why-h">
          <h2 id="why-h">Why this exists</h2>
          <p style={{ marginTop: "1rem" }}>Sports coverage follows crowds. Athletes who train on dirt tracks, play for small clubs or win away from the big cities can earn a single article and then vanish. This project is an attempt to surface those stories, explain why each was picked, and point readers to the original reporting.</p>
          <p className="muted">It is a screening aid, not a verdict. Every story links to its source so you can judge it yourself.</p>
        </section>
      </div>
    </>
  );
}
