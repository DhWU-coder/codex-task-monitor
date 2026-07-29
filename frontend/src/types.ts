export type TaskStatus =
  | "running"
  | "waiting_approval"
  | "waiting_input"
  | "completed"
  | "failed"
  | "interrupted"
  | "unknown"
  | "source_error"

export type WatchMode = "current_turn" | "persistent"

export interface TaskSnapshot {
  thread_id: string
  turn_id: string | null
  title: string
  status: TaskStatus
  source: "app_server" | "session" | "merged"
  project_name: string | null
  cwd: string | null
  branch: string | null
  source_label: string
  started_at: string | null
  completed_at: string | null
  updated_at: string
  latest_summary: string
  waiting_reason: string
  request_id: string | null
  error_summary: string
  monitored: boolean
  watch_mode: WatchMode | null
}

export interface SourceHealth {
  name: string
  connected: boolean
  message: string
  updated_at: string
}

export interface PublicConfig {
  server: {
    host: "127.0.0.1" | "localhost" | "::1"
    port: number
  }
  codex: {
    command: string
    refresh_interval_seconds: number
    reconcile_interval_seconds: number
    recent_completed_hours: number
  }
  feishu: {
    app_id: string
    app_secret: string
    app_secret_configured: boolean
    receive_id: string
    receive_id_type: "open_id" | "union_id" | "user_id" | "email"
  }
  notifications: {
    enabled: boolean
    summary_max_length: number
    notify_completed: boolean
    notify_failed: boolean
    notify_interrupted: boolean
    notify_waiting_input: boolean
    notify_waiting_approval: boolean
  }
  restart_required?: boolean
}

export interface HealthResponse {
  status: "ok"
  sources: Record<string, SourceHealth>
}
