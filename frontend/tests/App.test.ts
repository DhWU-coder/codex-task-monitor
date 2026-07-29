import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import App from "../src/App.vue"
import type {
  HealthResponse,
  PublicConfig,
  TaskSnapshot,
} from "../src/types"

const apiMocks = vi.hoisted(() => ({
  getTasks: vi.fn(),
  getHealth: vi.fn(),
  getConfig: vi.fn(),
  startWatch: vi.fn(),
  stopWatch: vi.fn(),
  createTaskEventSource: vi.fn(),
}))

vi.mock("../src/api", () => apiMocks)

class FakeEventSource {
  listeners = new Map<string, (event: MessageEvent) => void>()
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  addEventListener(
    type: string,
    listener: (event: MessageEvent) => void,
  ): void {
    this.listeners.set(type, listener)
  }

  close(): void {
    this.closed = true
  }

  emit(type: string, payload: unknown): void {
    this.listeners.get(type)?.(
      new MessageEvent(type, { data: JSON.stringify(payload) }),
    )
  }
}

const baseTask: TaskSnapshot = {
  thread_id: "thread-running",
  turn_id: "turn-1",
  title: "实现任务监控器",
  status: "running",
  source: "merged",
  project_name: "codex-task-monitor",
  cwd: "/work/codex-task-monitor",
  branch: "feature/monitor",
  source_label: "Codex",
  started_at: "2026-07-29T09:00:00Z",
  completed_at: null,
  updated_at: "2026-07-29T09:01:00Z",
  latest_summary: "正在实现任务卡片。",
  waiting_reason: "",
  request_id: null,
  error_summary: "",
  monitored: false,
  watch_mode: null,
}

const waitingTask: TaskSnapshot = {
  ...baseTask,
  thread_id: "thread-waiting",
  title: "等待用户确认",
  status: "waiting_approval",
  waiting_reason: "需要允许执行测试。",
}

const completedTask: TaskSnapshot = {
  ...baseTask,
  thread_id: "thread-completed",
  title: "已经完成的任务",
  status: "completed",
  completed_at: "2026-07-29T09:02:00Z",
}

const health: HealthResponse = {
  status: "ok",
  sources: {
    app_server: {
      name: "app_server",
      connected: true,
      message: "",
      updated_at: "2026-07-29T09:00:00Z",
    },
    session_observer: {
      name: "session_observer",
      connected: true,
      message: "",
      updated_at: "2026-07-29T09:00:00Z",
    },
  },
}

const publicConfig = {
  feishu: {
    app_secret_configured: true,
  },
} as PublicConfig

let wrappers: VueWrapper[] = []
let source: FakeEventSource

async function renderApp(): Promise<VueWrapper> {
  const wrapper = mount(App)
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  source = new FakeEventSource()
  apiMocks.getTasks.mockResolvedValue([
    baseTask,
    waitingTask,
    completedTask,
  ])
  apiMocks.getHealth.mockResolvedValue(health)
  apiMocks.getConfig.mockResolvedValue(publicConfig)
  apiMocks.startWatch.mockResolvedValue({ ok: true, mode: "persistent" })
  apiMocks.stopWatch.mockResolvedValue({ ok: true })
  apiMocks.createTaskEventSource.mockReturnValue(source)
})

afterEach(() => {
  for (const wrapper of wrappers) {
    wrapper.unmount()
  }
  wrappers = []
  vi.clearAllMocks()
})

describe("任务监控主页面", () => {
  it("默认只显示运行中的任务", async () => {
    const wrapper = await renderApp()

    expect(wrapper.text()).toContain("实现任务监控器")
    expect(wrapper.text()).not.toContain("等待用户确认")
    expect(wrapper.get('[aria-current="page"]').text()).toContain("运行中")
  })

  it("需处理筛选只显示等待任务", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-filter='attention']").trigger("click")

    expect(wrapper.text()).toContain("等待用户确认")
    expect(wrapper.text()).not.toContain("实现任务监控器")
  })

  it("任务卡片展示项目分支和两种监控操作", async () => {
    const wrapper = await renderApp()

    expect(wrapper.text()).toContain("codex-task-monitor")
    expect(wrapper.text()).toContain("feature/monitor")
    expect(wrapper.get("button[data-watch='current_turn']").exists()).toBe(true)
    expect(wrapper.get("button[data-watch='persistent']").exists()).toBe(true)

    await wrapper.get("button[data-watch='persistent']").trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-running",
      "persistent",
    )
    expect(wrapper.text()).toContain("停止监控")
  })

  it("详情展示任务安全摘要", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-action='details']").trigger("click")

    expect(wrapper.get("[role='dialog']").text()).toContain(
      "正在实现任务卡片。",
    )
    expect(wrapper.get("[role='dialog']").text()).toContain(
      "/work/codex-task-monitor",
    )
  })

  it("SSE 任务快照替换当前卡片", async () => {
    const wrapper = await renderApp()
    const replacement = {
      ...baseTask,
      title: "来自实时事件的新任务",
    }

    source.emit("tasks", { tasks: [replacement] })
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain("来自实时事件的新任务")
    expect(wrapper.text()).not.toContain("实现任务监控器")
  })
})
