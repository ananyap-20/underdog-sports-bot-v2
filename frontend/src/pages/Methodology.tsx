import type { Methodology as M } from "../api";
import { useApi } from "../hooks";
import { ErrorBox, Skeletons } from "../components/ui";

export default function Methodology() {
  const { data: m, error, loading, retry } = useApi<M>("/api/methodology");
  return (
    <div className="wrap section prose" style={{ borderTop: 0 }}>
      <h1 style={{ fontSize: "clamp(2.2rem,5vw,3.6rem)" }}>How it works</h1>
      <p style={{ marginTop: "1rem" }}>Everything here describes what the code in the repository actually does. Rules and weights below are served by the API, not typed into the page.</p>

      <h2>The pipeline</h2>
      <h3>1. News discovery</h3><p>Searches NewsAPI with a set of Indian-sports queries over a configurable window (default 7 days). If NewsAPI is unavailable or out of quota, a Google News RSS fallback is used. Coverage is limited to what these sources return.</p>
      <h3>2. Indian-sports relevance</h3><p>A strict keyword-based check keeps articles about Indian sports, then duplicates are removed by normalised title and URL.</p>
      <h3>3. Enrichment</h3><p>Article page text and source evidence are attached, and resource-constraint and narrative evidence is searched for.</p>
      <h3>4. Underdog signal analysis</h3><p>spaCy-based extraction produces entities and achievement, underdog, coverage-gap and status-gap scores.</p>
      <h3>5. Public-attention checks</h3><p>A read-only Reddit search counts matching discussions, with an RSS fallback. A low count is treated as an attention gap (F). A failed check is recorded as unknown, never as a negative finding.</p>
      <h3>6. Qualification</h3>
      {loading && <Skeletons n={2} />}
      {error && <ErrorBox error={error} retry={retry} />}
      {m && (
        <>
          <table><thead><tr><th>Category</th><th>Rule</th></tr></thead>
            <tbody>{m.category_rules.map((r) => <tr key={r.code}><td>{r.label} <span className="muted">({r.code})</span></td><td>{r.rule}</td></tr>)}</tbody></table>
          <p style={{ marginTop: "1rem" }}><b>No score gate.</b> {m.no_score_gate}</p>
          <h3>Rank score weights</h3>
          <table><thead><tr><th>Stage</th><th>Weights</th></tr></thead>
            <tbody>{m.score_formulas.map((f) => <tr key={f.stage}><td>{f.stage}</td><td>{Object.entries(f.weights).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}</td></tr>)}</tbody></table>
          <p className="small muted" style={{ marginTop: ".6rem" }}>{m.config.note} (settings: final {m.config.min_final_score_setting}, achievement {m.config.min_achievement_score_setting}).</p>
        </>
      )}
      <h3>7. Presentation and support</h3><p>Qualified stories are saved to <code>data/processed/latest_qualified.json</code>. This site only reads that file. Support links appear only when a hand-verified entry in the support registry is tied to the same athlete or team.</p>

      <h2>Known limitations</h2>
      <ul>
        <li>Keyword and NLP rules produce false positives (stories that are not really underdog stories) and false negatives (stories that are missed).</li>
        <li>Only stories surfaced by the configured news sources are seen. Regional-language coverage is likely under-represented.</li>
        <li>Reddit is a narrow slice of public discussion. Low Reddit discussion is not proof that a story is unimportant.</li>
        <li>API failures and rate limits are shown as unknown, never as a finding.</li>
        <li>Automated screening is not human verification. Check the original report before sharing or donating.</li>
      </ul>
    </div>
  );
}
