import { Link, useParams } from "react-router-dom";
import type { SupportLink, StoryDetail } from "../api";
import { useApi } from "../hooks";
import { fmtDate, fmtDateTime, pct } from "../format";
import { AttentionBadge, CategoryBadge, Cover, ErrorBox, FreshnessBanner, Skeletons, Unavailable } from "../components/ui";

const SUPPORT_GROUPS: Record<string, string> = {
  donate_campaign: "Donate to an authorised campaign", team_support: "Support a team or academy",
  sponsor_athlete: "Sponsor an athlete", official_initiative: "Contribute to an official sports initiative",
  equipment_training: "Equipment or training support", official_profile: "Official profile (not a donation page)",
};

function Bar({ label, value, hint }: { label: string; value: number | null; hint: string }) {
  return (
    <div className="bar" title={hint}>
      <span>{label}</span>
      <i role="img" aria-label={value === null ? "not collected" : pct(value)}>{value !== null && <u style={{ width: pct(Math.min(1, Math.max(0, value))) }} />}</i>
      <span>{value === null ? "n/a" : value.toFixed(2)}</span>
    </div>
  );
}

function attentionExplanation(s: StoryDetail): string {
  const a = s.attention;
  if (a.status === "unknown") return "The Reddit check did not return a discussion count, so this is unknown. A failed or rate-limited check does not mean nobody cares about this story.";
  if (a.status === "gap_found") return "The check found little or no matching Reddit discussion. That is one limited signal of low attention, not proof that nobody is talking about it.";
  return "The check found matching Reddit discussion, so this story does not count as an attention gap.";
}

function Support({ s }: { s: StoryDetail }) {
  const groups = s.support_links.reduce<Record<string, SupportLink[]>>((acc, l) => { (acc[l.category] ??= []).push(l); return acc; }, {});
  return (
    <section className="panel" aria-labelledby="back-h">
      <h3 id="back-h">Back their journey</h3>
      <p className="small muted">If this story inspired you, explore official channels through which you may be able to support the athlete, team or their sporting journey.</p>
      {s.support_links.length === 0 ? (
        <div className="notice">No verified support destination is on file for this story. The original article is linked above; checking the athlete's or team's official channels is the safest next step. We never guess donation links.</div>
      ) : (
        Object.entries(groups).map(([cat, links]) => (
          <div key={cat}>
            <h4 className="ui" style={{ fontSize: "1rem", margin: "1rem 0 .4rem" }}>{SUPPORT_GROUPS[cat] ?? cat}</h4>
            {links.map((l) => (
              <div key={l.url} className="card" style={{ marginBottom: ".6rem" }}>
                <b className="ui">{l.title ?? l.recipient}</b>
                <dl>
                  <dt>Recipient</dt><dd>{l.recipient}</dd>
                  <dt>Relationship</dt><dd>{l.relationship}</dd>
                  <dt>Leads to</dt><dd>{new URL(l.url).hostname}</dd>
                  <dt>Verified</dt><dd>{l.last_verified} (<a href={l.evidence_url} target="_blank" rel="noopener noreferrer">evidence</a>)</dd>
                  {l.restrictions && (<><dt>Restrictions</dt><dd>{l.restrictions}</dd></>)}
                </dl>
                <div><a className="btn small primary" href={l.url} target="_blank" rel="noopener noreferrer nofollow">{cat === "official_profile" ? "Visit official profile" : "Visit external page"}</a></div>
              </div>
            ))}
          </div>
        ))
      )}
      <p className="small muted" style={{ marginTop: "1rem" }}>Support opportunities are provided through external organisations or campaigns. Please verify the recipient, eligibility, terms and use of funds before contributing. Underdog Sports Bot does not process these payments, does not guarantee that funds reach an athlete, and does not endorse an external page by linking to it.</p>
    </section>
  );
}

export default function StoryPage() {
  const { id = "" } = useParams();
  const { data: s, error, loading, retry } = useApi<StoryDetail>(`/api/stories/${encodeURIComponent(id)}`);
  return (
    <>
      {s && <FreshnessBanner f={s.freshness} />}
      <div className="wrap section" style={{ borderTop: 0 }}>
        <Link className="crumb" to="/stories">← All stories</Link>
        {loading && <div style={{ marginTop: "1.5rem" }}><Skeletons n={2} /></div>}
        {error && <div style={{ marginTop: "1.5rem" }}><ErrorBox error={error} retry={retry} /></div>}
        {s && (
          <>
            <header style={{ margin: "1.5rem 0 2rem" }}>
              <Cover s={s} tall />
              <div className="row" style={{ marginBottom: ".8rem" }}><CategoryBadge c={s.category} /><AttentionBadge s={s.attention.status} /></div>
              <h1 style={{ fontSize: "clamp(2rem,4.6vw,3.4rem)" }}>{s.title}</h1>
              <div className="meta" style={{ marginTop: "1rem", fontSize: ".95rem" }}>
                {s.entities.length > 0 && <span>{s.entities.join(", ")}</span>}
                {s.source_name && <span>{s.source_name}</span>}
                {fmtDate(s.published_at) && <span>{fmtDate(s.published_at)}</span>}
                {s.freshness.generated_at && <span>Processed {fmtDateTime(s.freshness.generated_at)}</span>}
              </div>
              {s.url ? <p style={{ marginTop: "1rem" }}><a className="btn primary" href={s.url} target="_blank" rel="noopener noreferrer">Read the original report</a></p> : <p className="muted">Original link unavailable.</p>}
            </header>

            <div className="two">
              <div>
                <section className="panel" aria-labelledby="why-h">
                  <h3 id="why-h">Why the bot selected this story</h3>
                  {s.description ? <p>{s.description}</p> : <p><Unavailable>The pipeline did not save an article summary for this story.</Unavailable></p>}
                  <p className="small muted">Selected as: <b>{s.category_label ?? "unclassified"}</b>. Evidence below is text the pipeline extracted, not independently verified claims.</p>
                  {s.evidence.resource && (<><b className="ui">Resource-constraint evidence (B)</b><blockquote>{s.evidence.resource}</blockquote></>)}
                  {s.evidence.narrative && (<><b className="ui">Underdog narrative evidence</b><blockquote>{s.evidence.narrative}</blockquote></>)}
                  {!s.evidence.resource && !s.evidence.narrative && <p><Unavailable>No evidence excerpt was saved.</Unavailable></p>}
                  {s.evidence.resource_origin && <p className="small muted">Evidence found in: {s.evidence.resource_origin}</p>}
                </section>

                <section className="panel" aria-labelledby="sc-h">
                  <h3 id="sc-h">Scoring transparency</h3>
                  <div className="bars">
                    <Bar label="Achievement" value={s.scores.achievement} hint="How remarkable the result looks. Higher means more." />
                    <Bar label="Underdog" value={s.scores.underdog} hint="Evidence of low resources, status or support. Higher means more." />
                    <Bar label="Coverage gap" value={s.scores.coverage_gap} hint="Evidence of limited news coverage. Higher means less coverage." />
                    <Bar label="Status gap" value={s.scores.status_gap} hint="Distance between the athlete or team and a favourite. Higher means more." />
                    <Bar label="Rank score" value={s.scores.combined} hint="Weighted sum, used only for ordering." />
                  </div>
                  <p className="small muted" style={{ marginTop: "1rem" }}>The rank score only orders stories that already passed the evidence rules. It is not a score threshold and not a measure of athletic quality. <Link to="/methodology">See the exact weights and rules.</Link></p>
                </section>
              </div>

              <div>
                <section className="panel" aria-labelledby="att-h">
                  <h3 id="att-h">Public-attention check</h3>
                  <p className="small">{attentionExplanation(s)}</p>
                  <dl>
                    <dt>Reddit discussions</dt><dd>{s.attention.status === "unknown" ? <Unavailable>unknown</Unavailable> : s.attention.reddit_discussion_count ?? <Unavailable>unknown</Unavailable>}</dd>
                    <dt>Total comments</dt><dd>{s.attention.status === "unknown" ? <Unavailable>unknown</Unavailable> : s.attention.reddit_total_comments ?? <Unavailable>unknown</Unavailable>}</dd>
                    <dt>Top post score</dt><dd>{s.attention.status === "unknown" ? <Unavailable>unknown</Unavailable> : s.attention.reddit_top_score ?? <Unavailable>unknown</Unavailable>}</dd>
                    <dt>Popularity</dt><dd>{s.attention.status === "unknown" ? <Unavailable>unknown</Unavailable> : s.attention.reddit_popularity}</dd>
                    <dt>News results</dt><dd>{s.coverage.news_result_count ?? <Unavailable>unknown</Unavailable>}</dd>
                  </dl>
                  {s.attention.note && <blockquote className="small">{s.attention.note}</blockquote>}
                  <p className="small muted">Individual discussion links are not saved, only aggregate counts. Reddit and RSS results are limited evidence, not a measure of real public interest.</p>
                </section>
                <Support s={s} />
                <section className="panel">
                  <h3>Something wrong?</h3>
                  <p className="small muted">Incorrect facts, broken links or a bad support link: <a href="https://github.com/ananyap-20/underdog-sports-bot-v2/issues" target="_blank" rel="noopener noreferrer">report it on GitHub</a>.</p>
                </section>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
