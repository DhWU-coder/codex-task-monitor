import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

import SettingsPanel from "../src/components/SettingsPanel.vue"
import type { PublicConfig } from "../src/types"

const apiMocks = vi.hoisted(() => ({
  updateConfig: vi.fn(),
  sendTestNotification: vi.fn(),
}))

vi.mock("../src/api", () => apiMocks)

const config: PublicConfig = {
  server: {
    host: "127.0.0.1",
    port: 6664,
  },
  codex: {
    command: "codex",
    refresh_interval_seconds: 2,
    reconcile_interval_seconds: 30,
    recent_completed_hours: 24,
  },
  feishu: {
    app_id: "cli_test",
    app_secret: "",
    app_secret_configured: true,
    receive_id: "ou_test",
    receive_id_type: "open_id",
  },
  notifications: {
    enabled: true,
    summary_max_length: 500,
    notify_completed: true,
    notify_failed: true,
    notify_interrupted: true,
    notify_waiting_input: true,
    notify_waiting_approval: true,
  },
}

beforeEach(() => {
  apiMocks.updateConfig.mockResolvedValue({ ...config })
  apiMocks.sendTestNotification.mockResolvedValue({ message_id: "om_test" })
  vi.restoreAllMocks()
})

describe("设置面板", () => {
  it("只显示密钥已配置状态，不回显密钥", () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })

    expect(wrapper.get("input[aria-label='端口']").element).toHaveProperty(
      "value",
      "6664",
    )
    expect(
      (wrapper.get("input[aria-label='飞书 App Secret']").element as HTMLInputElement)
        .value,
    ).toBe("")
    expect(wrapper.text()).toContain("密钥已配置")
    expect(wrapper.html()).not.toContain("real-secret")
  })

  it("保存端口并展示重启提示", async () => {
    apiMocks.updateConfig.mockResolvedValue({
      ...config,
      server: { ...config.server, port: 6670 },
      restart_required: true,
    })
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })
    await wrapper.get("input[aria-label='端口']").setValue("6670")

    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(apiMocks.updateConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        server: expect.objectContaining({ port: 6670 }),
      }),
    )
    expect(wrapper.text()).toContain("codex-task-monitor restart")
  })

  it("空密钥默认保留，只有勾选后显式清除", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })

    await wrapper.get("form").trigger("submit")
    await flushPromises()
    expect(apiMocks.updateConfig.mock.calls[0][0].feishu).toMatchObject({
      app_secret: "",
      clear_app_secret: false,
    })

    await wrapper.get("input[aria-label='清除已保存密钥']").setValue(true)
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(apiMocks.updateConfig.mock.calls[1][0].feishu).toMatchObject({
      clear_app_secret: true,
    })
  })

  it("确认后发送测试消息并展示结果", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })

    await wrapper.get("button[data-action='test-notification']").trigger("click")
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    expect(apiMocks.sendTestNotification).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain("测试消息已发送")
  })

  it("展示保存错误且不关闭面板", async () => {
    apiMocks.updateConfig.mockRejectedValue(new Error("端口无效"))
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })

    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(wrapper.get("[role='alert']").text()).toContain("端口无效")
    expect(wrapper.emitted("close")).toBeUndefined()
  })
})
