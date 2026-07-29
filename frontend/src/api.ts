import type {
  HealthResponse,
  PublicConfig,
  TaskSnapshot,
  WatchMode,
} from "./types"

interface MessageResponse {
  message_id: string
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
  })
  const contentType = response.headers.get("Content-Type") ?? ""
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null
  if (!response.ok) {
    const detail = payload?.detail
    const message =
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `请求失败（${response.status}）`
    throw new Error(message)
  }
  return payload as T
}

function csrfToken(): string {
  const prefix = "codex_monitor_csrf="
  const match = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix))
  return match ? decodeURIComponent(match.slice(prefix.length)) : ""
}

function mutationOptions(
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): RequestInit {
  const options: RequestInit = {
    method,
    headers: {
      "X-CSRF-Token": csrfToken(),
    },
  }
  if (body !== undefined) {
    options.headers = {
      ...options.headers,
      "Content-Type": "application/json",
    }
    options.body = JSON.stringify(body)
  }
  return options
}

export async function getTasks(): Promise<TaskSnapshot[]> {
  const response = await request<{ tasks: TaskSnapshot[] }>("/api/tasks")
  return response.tasks
}

export function getTask(threadId: string): Promise<TaskSnapshot> {
  return request(`/api/tasks/${encodeURIComponent(threadId)}`)
}

export function startWatch(
  threadId: string,
  mode: WatchMode,
): Promise<{ ok: boolean; mode: WatchMode }> {
  return request(
    `/api/tasks/${encodeURIComponent(threadId)}/watch`,
    mutationOptions("POST", { mode }),
  )
}

export function stopWatch(
  threadId: string,
): Promise<{ ok: boolean }> {
  return request(
    `/api/tasks/${encodeURIComponent(threadId)}/watch`,
    mutationOptions("DELETE"),
  )
}

export function getConfig(): Promise<PublicConfig> {
  return request("/api/config")
}

export function updateConfig(
  changes: Record<string, unknown>,
): Promise<PublicConfig> {
  return request("/api/config", mutationOptions("PUT", changes))
}

export function getHealth(): Promise<HealthResponse> {
  return request("/healthz")
}

export function sendTestNotification(): Promise<MessageResponse> {
  return request(
    "/api/notifications/test",
    mutationOptions("POST", {}),
  )
}

export function retryNotification(
  notificationId: number,
): Promise<MessageResponse> {
  return request(
    `/api/notifications/${notificationId}/retry`,
    mutationOptions("POST", {}),
  )
}

export function createTaskEventSource(): EventSource {
  return new EventSource("/api/events")
}
