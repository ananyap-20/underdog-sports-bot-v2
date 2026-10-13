import { fmtDate, pct } from "./format";
test("fmtDate handles null and garbage", () => {
  expect(fmtDate(null)).toBeNull();
  expect(fmtDate("not a date")).toBeNull();
  expect(fmtDate("2026-10-02T08:00:00Z")).toContain("2026");
});
test("pct", () => expect(pct(0.714)).toBe("71%"));
