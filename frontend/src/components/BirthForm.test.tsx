import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { BirthForm } from "./BirthForm";

test("省市联动并提交后端要求的 ChartRequest", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("provinces")) return new Response(JSON.stringify([{ code: "31", name: "上海市" }]), { status: 200 });
    if (url.includes("cities")) return new Response(JSON.stringify([{ code: 3101, name: "上海市", longitude: 121.47, latitude: 31.23 }]), { status: 200 });
    throw new Error(`unexpected ${url}`);
  });
  const submit = vi.fn();
  const user = userEvent.setup();
  render(<BirthForm busy={null} onSubmit={submit} />);

  await user.selectOptions(await screen.findByLabelText("出生省份"), "上海市");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("province=%E4%B8%8A%E6%B5%B7%E5%B8%82"), expect.anything()));
  await user.selectOptions(await screen.findByLabelText("出生城市"), "3101");
  await user.type(screen.getByLabelText(/姓名/), "测试用户");
  await user.click(screen.getByRole("button", { name: "请选择出生日期与时间" }));
  await user.selectOptions(screen.getByLabelText("年"), "1988");
  await user.selectOptions(screen.getByLabelText("月"), "7");
  await user.selectOptions(screen.getByLabelText("日"), "10");
  await user.selectOptions(screen.getByLabelText("分"), "30");
  await user.click(screen.getByRole("button", { name: "确定" }));
  await user.click(screen.getByRole("checkbox", { name: /我已阅读并同意/ }));
  await user.click(screen.getByRole("button", { name: "开始排盘" }));

  expect(submit).toHaveBeenCalledWith({
    name: "测试用户",
    gender: "male",
    birth_local_datetime: "1988-07-10T12:30",
    location_id: 3101,
  }, "chart");
});
