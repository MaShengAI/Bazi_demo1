export type ReviewProfile = {
  nickname: string; avatar_url: string | null; gender: string; cohort: string;
  day_master: string; zodiac: string; pillars: string[]; province: string;
};
export type Review = {
  id: string; profile: ReviewProfile; rating: number; face: string; content: string;
  created_at: string; status?: string; job_id?: string;
};
export type ReviewList = { items: Review[]; total: number; page: number; page_size: number };
export type ReviewChoice = { job_id: string; name: string; profile: ReviewProfile; review: Review | null };
export type ReviewOptions = { items: ReviewChoice[]; consent_version: string };
export const reviewFaces = ["😞", "😕", "🙂", "😊", "😄"];
export const reviewStatuses: Record<string, string> = { pending: "待审核", approved: "已通过", hidden: "已隐藏" };
export async function reviewRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch("/api/v1/" + path, {
    ...init, credentials: "same-origin", cache: "no-store",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error?.message || "暂时无法完成操作，请稍后重试。");
  return data as T;
}
export function reviewTextLength(text: string): number {
  const Segmenter = (Intl as unknown as { Segmenter?: new (locale: string, options: { granularity: string }) => { segment(text: string): Iterable<unknown> } }).Segmenter;
  if (Segmenter) return Array.from(new Segmenter("zh", { granularity: "grapheme" }).segment(text)).length;
  const clusters: string[] = []; let regional = 0;
  for (const char of text) {
    const code = char.codePointAt(0)!;
    const flag = code >= 0x1f1e6 && code <= 0x1f1ff;
    const extend = /\p{Mark}/u.test(char) || char === "\u200d" || (code >= 0x1f3fb && code <= 0x1f3ff) || (code >= 0xe0020 && code <= 0xe007f) || clusters.at(-1)?.endsWith("\u200d") || (flag && regional % 2 === 1);
    if (clusters.length && extend) clusters[clusters.length - 1] += char; else clusters.push(char);
    regional = flag ? regional + 1 : 0;
  }
  return clusters.length;
}
