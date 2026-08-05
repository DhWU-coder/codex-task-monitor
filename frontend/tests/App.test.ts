import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import App from "../src/App.vue"
import { THEME_STORAGE_KEY } from "../src/theme"
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
  markManualCompletion: vi.fn(),
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

class FakeStorage implements Storage {
  private values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

class FakeMediaQueryList {
  matches = false
  listeners = new Set<(event: MediaQueryListEvent) => void>()

  addEventListener(
    type: string,
    listener: (event: MediaQueryListEvent) => void,
  ): void {
    if (type === "change") {
      this.listeners.add(listener)
    }
  }

  removeEventListener(
    type: string,
    listener: (event: MediaQueryListEvent) => void,
  ): void {
    if (type === "change") {
      this.listeners.delete(listener)
    }
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
let themeMediaQuery: FakeMediaQueryList

async function renderApp(): Promise<VueWrapper> {
  const wrapper = mount(App)
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

async function openTaskContextMenu(
  wrapper: VueWrapper,
  card = wrapper.get(".task-card"),
): Promise<MouseEvent> {
  const event = new MouseEvent("contextmenu", {
    bubbles: true,
    cancelable: true,
    clientX: 80,
    clientY: 100,
  })
  card.element.dispatchEvent(event)
  await wrapper.vm.$nextTick()
  return event
}

async function chooseManualCompletion(
  wrapper: VueWrapper,
): Promise<void> {
  await openTaskContextMenu(wrapper)
  const action = document.querySelector(
    "[data-action='context-manual-completion']",
  ) as HTMLButtonElement
  action.click()
  await wrapper.vm.$nextTick()
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: new FakeStorage(),
  })
  themeMediaQuery = new FakeMediaQueryList()
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => themeMediaQuery as unknown as MediaQueryList),
  })
  delete document.documentElement.dataset.theme
  document.documentElement.style.colorScheme = ""
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
  apiMocks.markManualCompletion.mockResolvedValue({
    ...baseTask,
    status: "manually_completed",
    completed_at: "2026-07-29T09:03:00Z",
  })
  apiMocks.createTaskEventSource.mockReturnValue(source)
})

afterEach(() => {
  for (const wrapper of wrappers) {
    wrapper.unmount()
  }
  wrappers = []
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe("任务监控主页面", () => {
  it("默认只显示运行中的任务", async () => {
    const wrapper = await renderApp()

    expect(wrapper.text()).toContain("实现任务监控器")
    expect(wrapper.text()).not.toContain("等待用户确认")
    expect(wrapper.get('[aria-current="page"]').text()).toContain("运行中")
  })

  it("任务使用单列横向列表结构", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      baseTask,
      {
        ...baseTask,
        thread_id: "thread-running-2",
        title: "第二个运行任务",
      },
    ])
    const wrapper = await renderApp()

    const taskList = wrapper.get("[data-task-list]")
    const rows = taskList.findAll(".task-card")

    expect(taskList.classes()).toContain("task-list")
    expect(wrapper.find(".task-grid").exists()).toBe(false)
    expect(rows).toHaveLength(2)
    for (const row of rows) {
      expect(row.find("[data-task-identity]").exists()).toBe(true)
      expect(row.find("[data-task-meta]").exists()).toBe(true)
      expect(row.find("[data-task-actions]").exists()).toBe(true)
    }
  })

  it("需处理筛选只显示等待任务", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-filter='attention']").trigger("click")

    expect(wrapper.text()).toContain("等待用户确认")
    expect(wrapper.text()).not.toContain("实现任务监控器")
  })

  it("监控中筛选展示活动和终态监控任务并支持停止", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        monitored: true,
        watch_mode: "current_turn",
      },
      waitingTask,
      {
        ...completedTask,
        monitored: true,
        watch_mode: "persistent",
      },
    ])
    const wrapper = await renderApp()

    const monitoredFilter = wrapper.get(
      "button[data-filter='monitored']",
    )
    expect(monitoredFilter.get(".filter-count").text()).toBe("2")

    await monitoredFilter.trigger("click")

    expect(wrapper.text()).toContain("实现任务监控器")
    expect(wrapper.text()).toContain("已经完成的任务")
    expect(wrapper.text()).not.toContain("等待用户确认")

    const completedCard = wrapper
      .findAll(".task-card")
      .find((card) => card.text().includes("已经完成的任务"))
    expect(completedCard).toBeDefined()

    await completedCard!.get("[data-action='stop']").trigger("click")
    await flushPromises()

    expect(apiMocks.stopWatch).toHaveBeenCalledWith("thread-completed")
    expect(wrapper.text()).not.toContain("已经完成的任务")
    expect(wrapper.text()).toContain("实现任务监控器")
    expect(monitoredFilter.get(".filter-count").text()).toBe("1")
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

  it("当前筛选操作默认显示并在选择模式隐藏", async () => {
    const wrapper = await renderApp()

    expect(
      wrapper.find("[aria-label='当前筛选批量监控']").exists(),
    ).toBe(true)

    await wrapper.get("[data-action='enter-selection']").trigger("click")

    expect(
      wrapper.find("[aria-label='当前筛选批量监控']").exists(),
    ).toBe(false)
  })

  it("当前筛选没有活动任务时禁用批量监控", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-filter='recent']").trigger("click")

    const currentTurnButton = wrapper.get(
      "[data-current-filter-watch='current_turn']",
    )
    const persistentButton = wrapper.get(
      "[data-current-filter-watch='persistent']",
    )
    expect(currentTurnButton.attributes("disabled")).toBeDefined()
    expect(persistentButton.attributes("disabled")).toBeDefined()

    await currentTurnButton.trigger("click")
    await persistentButton.trigger("click")

    expect(apiMocks.startWatch).not.toHaveBeenCalled()
  })

  it("当前筛选批量当前轮监控不重复请求且不降级持续监控", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-unwatched",
        title: "未监控任务",
      },
      {
        ...baseTask,
        thread_id: "thread-current",
        title: "当前轮任务",
        monitored: true,
        watch_mode: "current_turn",
      },
      {
        ...baseTask,
        thread_id: "thread-persistent",
        title: "持续任务",
        monitored: true,
        watch_mode: "persistent",
      },
    ])
    const wrapper = await renderApp()

    await wrapper
      .get("[data-current-filter-watch='current_turn']")
      .trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledTimes(1)
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-unwatched",
      "current_turn",
    )
    expect(apiMocks.startWatch).not.toHaveBeenCalledWith(
      "thread-persistent",
      "current_turn",
    )
    expect(wrapper.text()).toContain("当前轮监控中")
    expect(wrapper.text()).toContain("持续监控中")
  })

  it("当前筛选为全部时只持续监控活动任务", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-filter='all']").trigger("click")
    await wrapper
      .get("[data-current-filter-watch='persistent']")
      .trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledTimes(2)
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-running",
      "persistent",
    )
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-waiting",
      "persistent",
    )
    expect(apiMocks.startWatch).not.toHaveBeenCalledWith(
      "thread-completed",
      "persistent",
    )
  })

  it("当前筛选持续监控升级未监控和当前轮任务", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-unwatched",
        title: "未监控任务",
      },
      {
        ...baseTask,
        thread_id: "thread-current",
        title: "当前轮任务",
        monitored: true,
        watch_mode: "current_turn",
      },
      {
        ...baseTask,
        thread_id: "thread-persistent",
        title: "持续任务",
        monitored: true,
        watch_mode: "persistent",
      },
    ])
    const wrapper = await renderApp()

    await wrapper
      .get("[data-current-filter-watch='persistent']")
      .trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledTimes(2)
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-unwatched",
      "persistent",
    )
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-current",
      "persistent",
    )
    expect(apiMocks.startWatch).not.toHaveBeenCalledWith(
      "thread-persistent",
      "persistent",
    )
    for (const badge of wrapper.findAll(".watch-badge")) {
      expect(badge.text()).toBe("持续监控中")
    }
  })

  it("当前筛选批量监控部分失败时保留成功结果并提示", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-success",
        title: "成功任务",
      },
      {
        ...baseTask,
        thread_id: "thread-failed",
        title: "失败任务",
      },
    ])
    apiMocks.startWatch.mockImplementation((threadId: string) => {
      if (threadId === "thread-failed") {
        return Promise.reject(new Error("飞书监控启动失败"))
      }
      return Promise.resolve({ ok: true, mode: "current_turn" })
    })
    const wrapper = await renderApp()

    await wrapper
      .get("[data-current-filter-watch='current_turn']")
      .trigger("click")
    await flushPromises()

    expect(wrapper.findAll(".watch-badge")).toHaveLength(1)
    expect(wrapper.get("[role='alert']").text()).toContain(
      "1 个任务启动监控失败",
    )
  })

  it("当前筛选批量请求期间禁用监控和选择按钮", async () => {
    let resolveWatch: (() => void) | undefined
    apiMocks.startWatch.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveWatch = () => resolve({
            ok: true,
            mode: "current_turn",
          })
        }),
    )
    const wrapper = await renderApp()

    await wrapper
      .get("[data-current-filter-watch='current_turn']")
      .trigger("click")
    await wrapper.vm.$nextTick()

    expect(
      wrapper
        .get("[data-current-filter-watch='current_turn']")
        .attributes("disabled"),
    ).toBeDefined()
    expect(
      wrapper
        .get("[data-current-filter-watch='persistent']")
        .attributes("disabled"),
    ).toBeDefined()
    expect(
      wrapper
        .get("[data-action='enter-selection']")
        .attributes("disabled"),
    ).toBeDefined()

    resolveWatch?.()
    await flushPromises()

    expect(
      wrapper
        .get("[data-current-filter-watch='current_turn']")
        .attributes("disabled"),
    ).toBeUndefined()
    expect(
      wrapper
        .get("[data-action='enter-selection']")
        .attributes("disabled"),
    ).toBeUndefined()
  })

  it("选择模式只为活动任务显示复选框", async () => {
    const wrapper = await renderApp()

    expect(wrapper.get("[data-action='enter-selection']").text()).toBe("选择")
    expect(wrapper.find("[data-task-selection]").exists()).toBe(false)
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(false)

    await wrapper.get("[data-action='enter-selection']").trigger("click")

    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(true)
    expect(
      wrapper.find("[data-task-selection='thread-running']").exists(),
    ).toBe(true)

    await wrapper.get("button[data-filter='all']").trigger("click")

    expect(
      wrapper.find("[data-task-selection='thread-waiting']").exists(),
    ).toBe(true)
    expect(
      wrapper.find("[data-task-selection='thread-completed']").exists(),
    ).toBe(false)
  })

  it("选择在筛选间保留并支持全选、清空和退出", async () => {
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper
      .get("[data-task-selection='thread-running']")
      .setValue(true)

    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 1 项",
    )

    await wrapper.get("button[data-filter='attention']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")

    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 2 项",
    )

    await wrapper.get("button[data-filter='running']").trigger("click")
    expect(
      (
        wrapper.get(
          "[data-task-selection='thread-running']",
        ).element as HTMLInputElement
      ).checked,
    ).toBe(true)

    await wrapper.get("[data-action='clear-selection']").trigger("click")
    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 0 项",
    )
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(true)

    await wrapper.get("[data-action='exit-selection']").trigger("click")
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(false)
    expect(wrapper.find("[data-task-selection]").exists()).toBe(false)
  })

  it("全选只选择当前筛选中的活动任务", async () => {
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper.get("button[data-filter='all']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")

    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 2 项",
    )
    expect(
      wrapper.find("[data-task-selection='thread-completed']").exists(),
    ).toBe(false)

    await wrapper.get("[data-action='clear-selection']").trigger("click")
    await wrapper.get("button[data-filter='running']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")

    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 1 项",
    )
  })

  it("SSE 终态更新会清理选择但保留选择模式", async () => {
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper
      .get("[data-task-selection='thread-running']")
      .setValue(true)

    source.emit("tasks", {
      tasks: [
        {
          ...baseTask,
          status: "completed",
          completed_at: "2026-07-29T09:04:00Z",
        },
      ],
    })
    await flushPromises()

    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 0 项",
    )
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(true)
  })

  it("批量当前轮监控不会降级已有持续监控", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-unwatched",
        title: "未监控任务",
      },
      {
        ...baseTask,
        thread_id: "thread-current",
        title: "当前轮任务",
        monitored: true,
        watch_mode: "current_turn",
      },
      {
        ...baseTask,
        thread_id: "thread-persistent",
        title: "持续任务",
        monitored: true,
        watch_mode: "persistent",
      },
    ])
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")
    await wrapper.get("[data-watch='current_turn']").trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledTimes(1)
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-unwatched",
      "current_turn",
    )
    expect(apiMocks.startWatch).not.toHaveBeenCalledWith(
      "thread-persistent",
      "current_turn",
    )
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(false)
    expect(wrapper.text()).toContain("当前轮监控中")
    expect(wrapper.text()).toContain("持续监控中")
  })

  it("批量持续监控会升级未监控和当前轮任务", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-unwatched",
        title: "未监控任务",
      },
      {
        ...baseTask,
        thread_id: "thread-current",
        title: "当前轮任务",
        monitored: true,
        watch_mode: "current_turn",
      },
      {
        ...baseTask,
        thread_id: "thread-persistent",
        title: "持续任务",
        monitored: true,
        watch_mode: "persistent",
      },
    ])
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")
    await wrapper.get("[data-watch='persistent']").trigger("click")
    await flushPromises()

    expect(apiMocks.startWatch).toHaveBeenCalledTimes(2)
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-unwatched",
      "persistent",
    )
    expect(apiMocks.startWatch).toHaveBeenCalledWith(
      "thread-current",
      "persistent",
    )
    expect(apiMocks.startWatch).not.toHaveBeenCalledWith(
      "thread-persistent",
      "persistent",
    )
    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(false)
    expect(wrapper.findAll(".watch-badge")).toHaveLength(3)
    for (const badge of wrapper.findAll(".watch-badge")) {
      expect(badge.text()).toBe("持续监控中")
    }
  })

  it("批量监控部分失败时只保留失败任务的选择", async () => {
    apiMocks.getTasks.mockResolvedValueOnce([
      {
        ...baseTask,
        thread_id: "thread-success",
        title: "成功任务",
      },
      {
        ...baseTask,
        thread_id: "thread-failed",
        title: "失败任务",
      },
    ])
    apiMocks.startWatch.mockImplementation((threadId: string) => {
      if (threadId === "thread-failed") {
        return Promise.reject(new Error("飞书监控启动失败"))
      }
      return Promise.resolve({ ok: true, mode: "current_turn" })
    })
    const wrapper = await renderApp()

    await wrapper.get("[data-action='enter-selection']").trigger("click")
    await wrapper.get("[data-action='select-all']").trigger("click")
    await wrapper.get("[data-watch='current_turn']").trigger("click")
    await flushPromises()

    expect(wrapper.find(".bulk-watch-bar").exists()).toBe(true)
    expect(wrapper.get(".bulk-watch-summary").text()).toContain(
      "已选择 1 项",
    )
    expect(
      (
        wrapper.get(
          "[data-task-selection='thread-success']",
        ).element as HTMLInputElement
      ).checked,
    ).toBe(false)
    expect(
      (
        wrapper.get(
          "[data-task-selection='thread-failed']",
        ).element as HTMLInputElement
      ).checked,
    ).toBe(true)
    expect(wrapper.get("[role='alert']").text()).toContain(
      "1 个任务启动监控失败",
    )
  })

  it("取消手动结束确认时不调用接口", async () => {
    const wrapper = await renderApp()

    expect(
      wrapper.find("[data-action='manual-completion']").exists(),
    ).toBe(false)

    await chooseManualCompletion(wrapper)

    const dialog = document.querySelector("[role='alertdialog']")
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    )
    const cancelButton = document.querySelector(
      "[data-action='confirm-dialog-cancel']",
    ) as HTMLButtonElement

    expect(dialog?.textContent).toContain("标记本轮已结束")
    expect(confirmButton?.classList.contains("button-danger")).toBe(true)

    cancelButton.click()
    await wrapper.vm.$nextTick()

    expect(apiMocks.markManualCompletion).not.toHaveBeenCalled()
    expect(document.querySelector("[role='alertdialog']")).toBeNull()
    expect(wrapper.text()).toContain("实现任务监控器")
  })

  it("确认手动结束后任务进入最近结束", async () => {
    const wrapper = await renderApp()

    await chooseManualCompletion(wrapper)
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    ) as HTMLButtonElement
    confirmButton.click()
    await flushPromises()

    expect(apiMocks.markManualCompletion).toHaveBeenCalledWith(
      "thread-running",
    )
    expect(document.querySelector("[role='alertdialog']")).toBeNull()
    expect(wrapper.text()).not.toContain("实现任务监控器")

    await wrapper.get("button[data-filter='recent']").trigger("click")

    expect(wrapper.text()).toContain("实现任务监控器")
    expect(wrapper.text()).toContain("手动结束")
  })

  it("手动结束失败时显示错误并恢复按钮", async () => {
    apiMocks.markManualCompletion.mockRejectedValueOnce(
      new Error("任务当前轮次已经结束"),
    )
    const wrapper = await renderApp()

    await chooseManualCompletion(wrapper)
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    ) as HTMLButtonElement
    confirmButton.click()
    await flushPromises()

    expect(wrapper.get("[role='alert']").text()).toContain(
      "任务当前轮次已经结束",
    )

    await openTaskContextMenu(wrapper)
    expect(
      (
        document.querySelector(
          "[data-action='context-manual-completion']",
        ) as HTMLButtonElement
      ).disabled,
    ).toBe(false)
  })

  it("终态任务和选择模式保留原生右键菜单", async () => {
    const wrapper = await renderApp()

    await wrapper.get("button[data-filter='all']").trigger("click")
    const terminalCard = wrapper
      .findAll(".task-card")
      .find((card) => card.text().includes("已经完成的任务"))
    expect(terminalCard).toBeDefined()

    const terminalEvent = await openTaskContextMenu(
      wrapper,
      terminalCard,
    )
    expect(terminalEvent.defaultPrevented).toBe(false)
    expect(
      document.querySelector("[role='menu']"),
    ).toBeNull()

    await wrapper.get("button[data-filter='running']").trigger("click")
    await wrapper.get("[data-action='enter-selection']").trigger("click")
    const selectionEvent = await openTaskContextMenu(wrapper)

    expect(selectionEvent.defaultPrevented).toBe(false)
    expect(
      document.querySelector("[role='menu']"),
    ).toBeNull()
  })

  it("进入选择模式会关闭已经打开的右键菜单", async () => {
    const wrapper = await renderApp()

    await openTaskContextMenu(wrapper)
    expect(document.querySelector("[role='menu']")).not.toBeNull()

    await wrapper.get("[data-action='enter-selection']").trigger("click")

    expect(document.querySelector("[role='menu']")).toBeNull()
  })

  it("SSE 终态更新会关闭任务右键菜单", async () => {
    const wrapper = await renderApp()

    await openTaskContextMenu(wrapper)
    expect(document.querySelector("[role='menu']")).not.toBeNull()

    source.emit("tasks", {
      tasks: [
        {
          ...baseTask,
          status: "completed",
          completed_at: "2026-07-29T09:04:00Z",
        },
      ],
    })
    await flushPromises()

    expect(document.querySelector("[role='menu']")).toBeNull()
    expect(
      document.querySelector("[role='alertdialog']"),
    ).toBeNull()
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

  it("使用太阳月亮按钮切换并保存主题", async () => {
    const wrapper = await renderApp()
    const toggle = wrapper.get("button[data-action='theme-toggle']")

    expect(toggle.attributes("aria-label")).toBe("切换到深色主题")
    expect(toggle.text()).toContain("☾")

    await toggle.trigger("click")
    expect(document.documentElement.dataset.theme).toBe("dark")
    expect(toggle.attributes("aria-label")).toBe("切换到浅色主题")
    expect(toggle.text()).toContain("☀")
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark")

    await toggle.trigger("click")
    expect(document.documentElement.dataset.theme).toBe("light")
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light")
  })

  it("卸载页面时停止监听系统主题", async () => {
    const wrapper = await renderApp()
    expect(themeMediaQuery.listeners.size).toBe(1)

    wrapper.unmount()

    expect(themeMediaQuery.listeners.size).toBe(0)
    wrappers = wrappers.filter((item) => item !== wrapper)
  })
})
