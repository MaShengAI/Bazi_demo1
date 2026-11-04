import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReviewCard, ReviewPage, PublicReviews } from "./ReviewPages";
import { reviewTextLength } from "../reviews";

const profile = { nickname: "👩🏽‍💻", avatar_url: null, gender: "female", cohort: "95后", day_master: "甲木", zodiac: "兔", pillars: ["甲子", "乙丑", "丙寅", "丁卯"], province: "湖北省" };
const review = { id: "review1", profile, rating: 1, face: "😞", content: "真实感受", created_at: "2026-11-02T00:00:00Z" };
afterEach(() => vi.unstubAllGlobals());

it("renders public report data, gender and all five rating positions", () => {
  render(<ReviewCard review={review} />);
  expect(screen.getAllByText("👩🏽‍💻").length).toBeGreaterThan(0);
  expect(screen.getByText("👩🏽‍💻**")).toBeInTheDocument();
  expect(screen.getByLabelText("女")).toBeInTheDocument();
  expect(screen.getByLabelText("1星")).toBeInTheDocument();
  expect(screen.getByText("95后")).toBeInTheDocument();
  expect(screen.getByText("生肖：兔")).toBeInTheDocument();
  expect(screen.getByText("日主：甲木")).toBeInTheDocument();
  expect(screen.queryByText(/95后.*\|/)).not.toBeInTheDocument();
  const score = screen.getByLabelText("1星");
  expect(score.querySelectorAll(".review-star")).toHaveLength(5);
  expect(score.querySelectorAll(".review-star.lit")).toHaveLength(1);
  expect(score.querySelector(".review-score-face")).toHaveTextContent("😞");
  expect(screen.queryByText(/星座/)).not.toBeInTheDocument();
  expect(reviewTextLength("👩🏽‍💻🇨🇳")).toBe(2);
});

it("submits directly without the removed notice, accepts one star and prevents repeated submissions", async () => {
  let resolvePost!: (value: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ job_id: "job1", name: "家人", profile, review: null }], consent_version: "review-public-v1" }) })
    .mockImplementationOnce(() => new Promise<Response>(resolve => { resolvePost = resolve; }));
  vi.stubGlobal("fetch", fetcher);
  const onSubmitted = vi.fn();
  const onReturn = vi.fn();
  render(<ReviewPage reportId="job1" auth={{ authenticated: true, enabled: true, user: { id: "u", display_name: "test", avatar_url: null } } as never} onLogin={vi.fn()} onSubmitted={onSubmitted} onReturn={onReturn} />);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText(/正在读取可评价报告/)).not.toBeInTheDocument();
  const text = await screen.findByLabelText("评价内容");
  fireEvent.change(text, { target: { value: "真实感受" } });
  fireEvent.click(screen.getByRole("radio", { name: /1星/ }));
  expect(screen.queryByText("公开资料预览")).not.toBeInTheDocument();
  expect(screen.queryByText("文字评价（2～100字）")).not.toBeInTheDocument();
  expect(text).toHaveAttribute("placeholder", "您的评价是我们前进的动力");
  expect(screen.queryByText(/提交即同意公开评价/)).not.toBeInTheDocument();
  const submit = screen.getByRole("button", { name: "提交评价" });
  fireEvent.click(submit); fireEvent.click(submit);
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("评价成功")).not.toBeInTheDocument();
  expect(JSON.parse(fetcher.mock.calls[1][1].body).rating).toBe(1);
  expect(JSON.parse(fetcher.mock.calls[1][1].body).consent).toBe(true);
  resolvePost({ ok: true, json: async () => ({ review: { ...review, status: "pending" } }) } as Response);
  expect(await screen.findByRole("heading", { name: "评价成功" })).toBeInTheDocument();
  expect(screen.queryByLabelText("评价内容")).not.toBeInTheDocument();
  expect(onSubmitted).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "返回报告" }));
  expect(onReturn).toHaveBeenCalledTimes(1);
});

it("keeps fast review reads quiet and shows only a delayed skeleton for slow reads", async () => {
  vi.useFakeTimers();
  try {
    let finish!: (value: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(resolve => { finish = resolve; })));
    render(<ReviewPage reportId="job1" auth={{ authenticated: true } as never} onLogin={vi.fn()} onSubmitted={vi.fn()} />);
    expect(screen.queryByText(/正在读取可评价报告/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "正在载入评价" })).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(449); });
    expect(screen.queryByRole("status", { name: "正在载入评价" })).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(screen.getByRole("status", { name: "正在载入评价" })).toBeInTheDocument();
    expect(screen.queryByText(/正在读取可评价报告/)).not.toBeInTheDocument();
    await act(async () => { finish({ ok: true, json: async () => ({ items: [{ job_id: "job1", name: "示例", profile, review: null }], consent_version: "review-public-v1" }) }); });
    expect(screen.queryByRole("status", { name: "正在载入评价" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("评价内容")).toBeInTheDocument();
  } finally { vi.useRealTimers(); }
});

it("does not show success on submission failure and keeps the draft for retry", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ job_id: "job1", name: "家人", profile, review: null }], consent_version: "review-public-v1" }) })
    .mockResolvedValueOnce({ ok: false, json: async () => ({ error: { message: "提交暂时失败" } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ review }) });
  vi.stubGlobal("fetch", fetcher);
  const onSubmitted = vi.fn();
  render(<ReviewPage reportId="job1" auth={{ authenticated: true } as never} onLogin={vi.fn()} onSubmitted={onSubmitted} />);
  fireEvent.change(await screen.findByLabelText("评价内容"), { target: { value: "重试时保留原文" } });
  fireEvent.click(screen.getByRole("button", { name: "提交评价" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("提交暂时失败");
  expect(screen.queryByText("评价成功")).not.toBeInTheDocument();
  expect(screen.getByLabelText("评价内容")).toHaveValue("重试时保留原文");
  expect(onSubmitted).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "提交评价" }));
  expect(await screen.findByRole("heading", { name: "评价成功" })).toBeVisible();
  expect(onSubmitted).toHaveBeenCalledTimes(1);
});

it("does not display approval notifications for an already submitted high rating", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ job_id: "job1", name: "家人", profile, review: { ...review, rating: 5, face: "😄", status: "approved" } }], consent_version: "review-public-v1" }) }));
  render(<ReviewPage reportId="job1" auth={{ authenticated: true } as never} onLogin={vi.fn()} onSubmitted={vi.fn()} />);
  expect(await screen.findByText("此报告已评价")).toBeVisible();
  expect(screen.queryByText(/已通过|自动审核|审核成功/)).not.toBeInTheDocument();
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("loads further public reviews only on request", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ items: [review], total: 11 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [{ ...review, id: "second", content: "第二页" }], total: 11 }) });
  vi.stubGlobal("fetch", fetcher);
  render(<PublicReviews />);
  await screen.findByText("真实感受");
  fireEvent.click(screen.getByRole("button", { name: /加载更多/ }));
  await waitFor(() => expect(fetcher.mock.calls[1][0]).toContain("page=2"));
  expect(await screen.findByText("第二页")).toBeInTheDocument();
});

it("短评由用户选择，保留原文、不重复添加且不超过100字", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ job_id: "job1", name: "家人", profile, review: null }], consent_version: "review-public-v1" }) }));
  render(<ReviewPage reportId="job1" auth={{ authenticated: true } as never} onLogin={vi.fn()} onSubmitted={vi.fn()} />);
  const text = await screen.findByLabelText("评价内容");
  expect(text).toHaveValue("");
  expect(screen.getAllByRole("radio")).toHaveLength(5);
  expect(screen.getByRole("radio", { name: "3星 一般，部分内容有帮助" })).toBeInTheDocument();
  const short = screen.getByRole("button", { name: "比预想的好。" });
  fireEvent.click(short);
  expect(text).toHaveValue("比预想的好。");
  fireEvent.click(short);
  expect(text).toHaveValue("比预想的好。");
  fireEvent.change(text, { target: { value: "这是我自己写的。" } });
  fireEvent.click(short);
  expect(text).toHaveValue("这是我自己写的。 比预想的好。");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  fireEvent.change(text, { target: { value: "字".repeat(99) } });
  fireEvent.click(short);
  expect(text).toHaveValue("字".repeat(99));
  expect(screen.getByRole("status")).toHaveTextContent("添加后将超过100字");
});
