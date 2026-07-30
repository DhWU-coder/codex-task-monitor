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
    orphaned_running_timeout_minutes: 60,
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

const emailConfig: PublicConfig = {
  ...config,
  feishu: {
    ...config.feishu,
    receive_id: "owner@company.com",
    receive_id_type: "email",
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

  it("显示并保存孤儿任务超时", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
    })
    const timeoutInput = wrapper.get(
      "input[aria-label='孤儿任务超时']",
    )
    expect((timeoutInput.element as HTMLInputElement).value).toBe("60")

    await timeoutInput.setValue("90")
    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(apiMocks.updateConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        codex: expect.objectContaining({
          orphaned_running_timeout_minutes: 90,
        }),
      }),
    )
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

  it("使用自定义确认弹窗发送测试消息", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: config },
      global: {
        stubs: { teleport: true },
      },
    })

    await wrapper.get("button[data-action='test-notification']").trigger("click")

    expect(wrapper.get("[role='alertdialog']").text()).toContain(
      "发送测试消息",
    )
    expect(apiMocks.sendTestNotification).not.toHaveBeenCalled()

    await wrapper
      .get("button[data-action='confirm-dialog-cancel']")
      .trigger("click")
    expect(wrapper.find("[role='alertdialog']").exists()).toBe(false)
    expect(apiMocks.sendTestNotification).not.toHaveBeenCalled()

    await wrapper.get("button[data-action='test-notification']").trigger("click")
    await wrapper
      .get("button[data-action='confirm-dialog-confirm']")
      .trigger("click")
    await flushPromises()

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

  it("推荐使用企业邮箱并展示邮箱输入提示", () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: emailConfig },
    })

    expect(wrapper.text()).toContain("推荐使用企业邮箱")
    const recipient = wrapper.get("input[aria-label='飞书企业邮箱']")
    expect(recipient.attributes("placeholder")).toBe("name@company.com")
    expect((recipient.element as HTMLInputElement).value).toBe(
      "owner@company.com",
    )
  })

  it("切换接收人类型后更新字段提示并保持保存结构", async () => {
    const wrapper = mount(SettingsPanel, {
      props: { initialConfig: emailConfig },
    })

    await wrapper
      .get("select[aria-label='飞书接收人 ID 类型']")
      .setValue("open_id")
    const recipient = wrapper.get("input[aria-label='飞书 Open ID']")
    expect(recipient.attributes("placeholder")).toBe("ou_xxxxxxxxxxxxxxxx")
    await recipient.setValue("ou_changed")

    await wrapper.get("form").trigger("submit")
    await flushPromises()

    expect(apiMocks.updateConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        feishu: expect.objectContaining({
          receive_id: "ou_changed",
          receive_id_type: "open_id",
        }),
      }),
    )
  })
})
