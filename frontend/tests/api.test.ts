import { afterEach, describe, expect, it, vi } from "vitest"

import type { TaskSnapshot } from "../src/types"

const task: TaskSnapshot = {
  thread_id: "thread-1",
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
  latest_summary: "正在实现。",
  waiting_reason: "",
  request_id: null,
  error_summary: "",
  monitored: false,
  watch_mode: null,
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = "codex_monitor_csrf=; Max-Age=0; Path=/"
})

describe("API 客户端", () => {
  it("读取任务安全投影", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tasks: [task] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)
    const { getTasks } = await import("../src/api")

    const tasks = await getTasks()

    expect(tasks).toEqual([task])
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tasks",
      expect.objectContaining({ credentials: "same-origin" }),
    )
  })

  it("修改请求携带 CSRF 和 JSON 头", async () => {
    document.cookie = "codex_monitor_csrf=csrf-test; Path=/"
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)
    const { startWatch } = await import("../src/api")

    await startWatch("thread-1", "persistent")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/tasks/thread-1/watch",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-test",
        }),
      }),
    )
  })

  it("把后端错误转换成可展示消息", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "任务不存在" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )
    const { getTask } = await import("../src/api")

    await expect(getTask("missing")).rejects.toThrow("任务不存在")
  })

  it("事件源使用同源 SSE 地址", async () => {
    const EventSourceMock = vi.fn()
    vi.stubGlobal("EventSource", EventSourceMock)
    const { createTaskEventSource } = await import("../src/api")

    createTaskEventSource()

    expect(EventSourceMock).toHaveBeenCalledWith("/api/events")
  })
})
