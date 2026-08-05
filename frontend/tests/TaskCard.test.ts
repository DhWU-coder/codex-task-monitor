import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import TaskCard from "../src/components/TaskCard.vue"
import type { TaskSnapshot } from "../src/types"

const baseTask: TaskSnapshot = {
  thread_id: "thread-running",
  turn_id: "turn-1",
  title: "轨迹解析 UI",
  status: "running",
  source: "merged",
  project_name: "beauty_agent",
  cwd: "/work/beauty_agent",
  branch: "wdh/beauty_agent_v2",
  source_label: "Codex",
  started_at: "2026-07-30T08:00:00Z",
  completed_at: null,
  updated_at: "2026-07-30T08:01:00Z",
  latest_summary: "这段普通摘要不应显示在紧凑任务行中。",
  waiting_reason: "",
  request_id: null,
  error_summary: "",
  monitored: true,
  watch_mode: "current_turn",
}

function renderTask(
  overrides: Partial<TaskSnapshot> = {},
  selectionMode = false,
  selectable = true,
) {
  return mount(TaskCard, {
    props: {
      task: { ...baseTask, ...overrides },
      busy: false,
      selectionMode,
      selected: false,
      selectable,
    },
  })
}

describe("紧凑任务行", () => {
  it("活动任务右击时阻止原生菜单并发出坐标", async () => {
    const wrapper = renderTask()
    const event = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
      clientX: 42,
      clientY: 71,
    })

    wrapper.get(".task-card").element.dispatchEvent(event)
    await wrapper.vm.$nextTick()

    expect(event.defaultPrevented).toBe(true)
    expect(wrapper.emitted("openContextMenu")).toEqual([
      [{ x: 42, y: 71 }],
    ])
  })

  it("选择模式和终态任务保留原生右键菜单", async () => {
    const selectionWrapper = renderTask({}, true)
    const selectionEvent = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
    })
    selectionWrapper
      .get(".task-card")
      .element.dispatchEvent(selectionEvent)
    await selectionWrapper.vm.$nextTick()

    expect(selectionEvent.defaultPrevented).toBe(false)
    expect(
      selectionWrapper.emitted("openContextMenu"),
    ).toBeUndefined()

    const terminalWrapper = renderTask(
      { status: "completed" },
      false,
      false,
    )
    const terminalEvent = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
    })
    terminalWrapper
      .get(".task-card")
      .element.dispatchEvent(terminalEvent)
    await terminalWrapper.vm.$nextTick()

    expect(terminalEvent.defaultPrevented).toBe(false)
    expect(
      terminalWrapper.emitted("openContextMenu"),
    ).toBeUndefined()
  })

  it("把状态标题和监控状态放在同一主行", () => {
    const wrapper = renderTask()
    const primary = wrapper.get("[data-task-primary]")

    expect(primary.text()).toContain("运行中")
    expect(primary.text()).toContain("轨迹解析 UI")
    expect(primary.text()).toContain("当前轮监控中")
    expect(wrapper.text()).toContain("beauty_agent")
    expect(wrapper.text()).toContain("wdh/beauty_agent_v2")
    expect(wrapper.text()).toContain("运行时长")
  })

  it("隐藏普通摘要和可见手动结束按钮", () => {
    const wrapper = renderTask()

    expect(wrapper.text()).not.toContain(
      "这段普通摘要不应显示在紧凑任务行中。",
    )
    expect(
      wrapper.find("[data-action='manual-completion']").exists(),
    ).toBe(false)
  })

  it("等待任务仍显示一行处理原因", () => {
    const wrapper = renderTask({
      status: "waiting_input",
      waiting_reason: "需要用户补充输入。",
    })

    expect(wrapper.get(".task-attention").text()).toBe(
      "需要用户补充输入。",
    )
  })

  it("终态任务仍被监控时可以停止监控", async () => {
    const wrapper = renderTask({
      status: "completed",
      completed_at: "2026-07-30T08:02:00Z",
      monitored: true,
      watch_mode: "persistent",
    })

    const stopButton = wrapper.get("[data-action='stop']")
    expect(stopButton.text()).toBe("停止监控")

    await stopButton.trigger("click")

    expect(wrapper.emitted("stop")).toHaveLength(1)
  })

  it("终态任务未被监控时不显示监控操作", () => {
    const wrapper = renderTask({
      status: "completed",
      completed_at: "2026-07-30T08:02:00Z",
      monitored: false,
      watch_mode: null,
    })

    expect(wrapper.find("[data-action='stop']").exists()).toBe(false)
    expect(wrapper.find("[data-watch='current_turn']").exists()).toBe(false)
    expect(wrapper.find("[data-watch='persistent']").exists()).toBe(false)
  })
})
