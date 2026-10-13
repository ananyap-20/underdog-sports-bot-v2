// Types mirror api/service.py::serialize. Nullable fields are really nullable: never assume presence.
export type Category = "B+F" | "B" | "F";
export type AttentionStatus = "gap_found" | "discussion_found" | "unknown";

export interface SupportLink {
  recipient: string; relationship: string; title: string | null; url: string;
  category: string; verification_status: string; evidence_url: string;
  last_verified: string; restrictions: string | null;
}
export interface Story {
  id: string; category: Category | null; category_label: string | null;
  title: string; url: string | null; entities: string[];
  description: string | null; image_url: string | null; published_at: string | null; source_name: string | null;
  matched_signals: string[];
  scores: { achievement: number; underdog: number; combined: number; coverage_gap: number | null; status_gap: number | null };
  evidence: { resource: string | null; resource_origin: string | null; narrative: string | null };
  attention: {
    status: AttentionStatus; gap_flag: boolean; reddit_discussion_count: number | null;
    reddit_total_comments: number | null; reddit_top_score: number | null;
    reddit_popularity: string; known_audience_size: number | null; note: string | null;
  };
  coverage: { result_count: number | null; news_result_count: number | null; domains: string[]; institutional_sources: string[]; social_sources: string[] };
  caption: string | null;
}
export interface Freshness { generated_at: string | null; age_hours: number | null; is_stale: boolean; is_demo: boolean }
export interface StoryDetail extends Story { support_links: SupportLink[]; freshness: Freshness }
export interface StoryList { items: Story[]; total: number; page: number; page_size: number; pages: number; available_sources: string[]; freshness: Freshness }
export interface Dashboard {
  freshness: Freshness; search_days_back: number | null; qualified_count: number;
  categories: Record<Category, number>; run_count: number; pipeline_funnel: null | Record<string, number>; featured: Story[];
}
export interface Methodology {
  category_rules: { code: string; label: string; rule: string }[];
  score_formulas: { stage: string; weights: Record<string, number> }[];
  no_score_gate: string; config: { min_final_score_setting: number; min_achievement_score_setting: number; note: string };
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string): Promise<T> {
  let res: Response;
  try { res = await fetch(path, { headers: { Accept: "application/json" } }); }
  catch { throw new ApiError("Could not reach the API. Is the backend running on port 8000?", 0); }
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try { const j = await res.json(); if (typeof j.detail === "string") detail = j.detail; } catch { /* keep default */ }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}
