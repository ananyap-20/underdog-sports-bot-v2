const REPO = "https://github.com/ananyap-20/underdog-sports-bot-v2";
export default function About() {
  return (
    <div className="wrap section prose" style={{ borderTop: 0 }}>
      <h1 style={{ fontSize: "clamp(2.2rem,5vw,3.6rem)" }}>About</h1>
      <p style={{ marginTop: "1rem" }}>Underdog Sports Bot is a student engineering project that looks for Indian sports stories which may have been overlooked, and explains why each one was picked. It is built to be transparent: every story links to its source and shows its evidence.</p>
      <h2>Technology</h2>
      <ul>
        <li>Python backend: NewsAPI ingestion, Google News RSS fallback, article enrichment</li>
        <li>spaCy (<code>en_core_web_sm</code>) for entity extraction and scoring</li>
        <li>Reddit read-only search and RSS for public-attention verification</li>
        <li>FastAPI read-only API over the pipeline's saved output</li>
        <li>React, TypeScript and Vite frontend</li>
      </ul>
      <h2>Engineering decisions</h2>
      <ul>
        <li>The website never re-runs the pipeline. It reads saved results, so page loads are fast and API keys stay on the backend.</li>
        <li>Missing data is shown as missing. Failed checks are never presented as findings.</li>
        <li>Support links live in a data file with verification evidence, and the API drops any link that fails validation.</li>
      </ul>
      <h2>Contribute</h2>
      <p><a href={REPO} target="_blank" rel="noopener noreferrer">Source on GitHub</a> · <a href={`${REPO}/issues`} target="_blank" rel="noopener noreferrer">Report an issue</a></p>
      <p className="small muted">No project sponsorship page has been configured. Supporting this project would not fund the athletes featured here.</p>
    </div>
  );
}
