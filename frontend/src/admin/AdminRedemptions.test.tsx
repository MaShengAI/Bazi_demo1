import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { AdminRedemptions } from "./AdminRedemptions";

const batch = { id: "batch", label: "测试批次", kind: "cards", value: 1, quantity: 4, created_at: "2026-11-03T00:00:00Z", expires_at: "2026-12-03T00:00:00Z" };
function mockList() {
  let rows = ["unused", "unused", "disabled", "redeemed"].map((status, i) => ({ id: String(i + 1).repeat(32), masked_code: `••••-ABC${i}`, status, batch, redeemed_by: status === "redeemed" ? "user" : null, redeemed_at: null, disabled_by: status === "disabled" ? "owner" : null }));
  const writes: { path: string; ids: string[] }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") {
      const ids = JSON.parse(String(init.body)).code_ids as string[];
      writes.push({ path, ids });
      if (path.endsWith("bulk-disable")) rows = rows.map(row => ids.includes(row.id) ? { ...row, status: "disabled" } : row);
      if (path.endsWith("bulk-delete")) rows = rows.filter(row => !ids.includes(row.id));
      return new Response(JSON.stringify({ changed: ids.length }));
    }
    const status = new URL(path, "http://localhost").searchParams.get("status");
    const items = rows.filter(row => !status || row.status === status);
    return new Response(JSON.stringify({ items, total: items.length, batches: [batch] }));
  });
  return writes;
}

test("勾选本页后批量停用，取消不写入，筛选后选择不会串页", async () => {
  const writes = mockList(); render(<AdminRedemptions />);
  await screen.findByText("共 4 个兑换码");
  fireEvent.click(screen.getByRole("checkbox", { name: "全选本页" }));
  expect(screen.getByRole("button", { name: "批量停用" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "批量删除" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("状态"), { target: { value: "unused" } });
  await screen.findByText("共 2 个兑换码");
  expect(screen.getByText("已选 0 个")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "全选本页" }));
  fireEvent.click(screen.getByRole("button", { name: "批量停用" }));
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "批量停用" }));
  const confirm = screen.getByRole("button", { name: "确认停用" });
  fireEvent.click(confirm); fireEvent.click(confirm);
  await screen.findByText("已停用 2 个兑换码。");
  expect(writes).toHaveLength(1);
  expect(writes[0].ids).toEqual(["1".repeat(32), "2".repeat(32)]);
  await screen.findByText("共 0 个兑换码");
});

test("已停用和已兑换支持批量删除，未兑换不能删除", async () => {
  const writes = mockList(); render(<AdminRedemptions />);
  await screen.findByText("共 4 个兑换码");
  fireEvent.click(screen.getByRole("checkbox", { name: "选择兑换码 ••••-ABC2" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "选择兑换码 ••••-ABC3" }));
  fireEvent.click(screen.getByRole("button", { name: "批量删除" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("已发放的解读卡、优惠券及兑换凭据仍保留");
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  await screen.findByText("已删除 2 个兑换码。");
  expect(writes).toHaveLength(1);
  expect(writes[0].path).toContain("bulk-delete");
  await waitFor(() => expect(screen.queryByRole("checkbox", { name: "选择兑换码 ••••-ABC2" })).not.toBeInTheDocument());
  expect(screen.getByRole("checkbox", { name: "选择兑换码 ••••-ABC0" })).toBeInTheDocument();
});
