export const fmtDate = (s: string | null | undefined): string | null => {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(+d) ? null : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
};
export const fmtDateTime = (s: string | null | undefined): string | null => {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(+d) ? null : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
};
export const pct = (n: number) => `${Math.round(n * 100)}%`;
