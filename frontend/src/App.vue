<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"

import {
  createTaskEventSource,
  getConfig,
  getHealth,
  getTasks,
  startWatch,
  stopWatch,
} from "./api"
import FilterTabs, {
  type TaskFilter,
} from "./components/FilterTabs.vue"
import SettingsPanel from "./components/SettingsPanel.vue"
import StatusBar from "./components/StatusBar.vue"
import TaskCard from "./components/TaskCard.vue"
import TaskDetails from "./components/TaskDetails.vue"
import type {
  PublicConfig,
  SourceHealth,
  TaskSnapshot,
  WatchMode,
} from "./types"

const tasks = ref<TaskSnapshot[]>([])
const sources = ref<Record<string, SourceHealth>>({})
const config = ref<PublicConfig | null>(null)
const activeFilter = ref<TaskFilter>("running")
const selectedTask = ref<TaskSnapshot | null>(null)
const settingsOpen = ref(false)
const loading = ref(true)
const errorMessage = ref("")
const busyTasks = ref(new Set<string>())
const liveStatus = ref<"connecting" | "connected" | "disconnected">(
  "connecting",
)

let eventSource: EventSource | null = null
let reconnectTimer: number | null = null
let reconnectAttempt = 0
let mounted = true

const activeStatuses = new Set([
  "running",
  "waiting_approval",
  "waiting_input",
])
const attentionStatuses = new Set(["waiting_approval", "waiting_input"])
const terminalStatuses = new Set(["completed", "failed", "interrupted"])

const counts = computed<Record<TaskFilter, number>>(() => ({
  running: tasks.value.filter((task) => task.status === "running").length,
  attention: tasks.value.filter((task) =>
    attentionStatuses.has(task.status),
  ).length,
  recent: tasks.value.filter((task) =>
    terminalStatuses.has(task.status),
  ).length,
  all: tasks.value.length,
}))

const visibleTasks = computed(() => {
  if (activeFilter.value === "running") {
    return tasks.value.filter((task) => task.status === "running")
  }
  if (activeFilter.value === "attention") {
    return tasks.value.filter((task) =>
      attentionStatuses.has(task.status),
    )
  }
  if (activeFilter.value === "recent") {
    return tasks.value.filter((task) =>
      terminalStatuses.has(task.status),
    )
  }
  return tasks.value
})

async function loadInitial(): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const [taskRows, health, publicConfig] = await Promise.all([
      getTasks(),
      getHealth(),
      getConfig(),
    ])
    tasks.value = taskRows
    sources.value = health.sources
    config.value = publicConfig
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "加载监控数据失败"
  } finally {
    loading.value = false
  }
}

function connectEvents(): void {
  if (!mounted) {
    return
  }
  liveStatus.value = "connecting"
  eventSource = createTaskEventSource()
  eventSource.onopen = () => {
    liveStatus.value = "connected"
    reconnectAttempt = 0
  }
  eventSource.addEventListener("tasks", (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as {
      tasks: TaskSnapshot[]
    }
    tasks.value = payload.tasks
  })
  eventSource.addEventListener("health", (event) => {
    const payload = JSON.parse((event as MessageEvent).data) as {
      sources: Record<string, SourceHealth>
    }
    sources.value = payload.sources
  })
  eventSource.onerror = () => {
    liveStatus.value = "disconnected"
    eventSource?.close()
    eventSource = null
    scheduleReconnect()
  }
}

function scheduleReconnect(): void {
  if (!mounted || reconnectTimer !== null) {
    return
  }
  const delay = Math.min(30_000, 1_000 * 2 ** reconnectAttempt)
  reconnectAttempt += 1
  reconnectTimer = window.setTimeout(async () => {
    reconnectTimer = null
    try {
      tasks.value = await getTasks()
    } catch {
      scheduleReconnect()
      return
    }
    connectEvents()
  }, delay)
}

async function watchTask(
  task: TaskSnapshot,
  mode: WatchMode,
): Promise<void> {
  if (!activeStatuses.has(task.status)) {
    return
  }
  setBusy(task.thread_id, true)
  errorMessage.value = ""
  try {
    await startWatch(task.thread_id, mode)
    replaceTask(task.thread_id, {
      monitored: true,
      watch_mode: mode,
    })
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "启动监控失败"
  } finally {
    setBusy(task.thread_id, false)
  }
}

async function stopTaskWatch(task: TaskSnapshot): Promise<void> {
  setBusy(task.thread_id, true)
  errorMessage.value = ""
  try {
    await stopWatch(task.thread_id)
    replaceTask(task.thread_id, {
      monitored: false,
      watch_mode: null,
    })
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "停止监控失败"
  } finally {
    setBusy(task.thread_id, false)
  }
}

function replaceTask(
  threadId: string,
  changes: Partial<TaskSnapshot>,
): void {
  tasks.value = tasks.value.map((task) =>
    task.thread_id === threadId ? { ...task, ...changes } : task,
  )
  if (selectedTask.value?.thread_id === threadId) {
    selectedTask.value = { ...selectedTask.value, ...changes }
  }
}

function setBusy(threadId: string, busy: boolean): void {
  const next = new Set(busyTasks.value)
  if (busy) {
    next.add(threadId)
  } else {
    next.delete(threadId)
  }
  busyTasks.value = next
}

onMounted(async () => {
  await loadInitial()
  connectEvents()
})

onUnmounted(() => {
  mounted = false
  eventSource?.close()
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
  }
})
</script>

<template>
  <div class="app-shell">
    <header class="page-header">
      <div>
        <p class="eyebrow">LOCAL CODEX OBSERVER</p>
        <h1>任务监控器</h1>
        <p class="page-subtitle">
          聚合本机 Codex 任务，在需要处理或任务结束时通知你。
        </p>
      </div>
      <button
        type="button"
        class="button button-secondary settings-button"
        @click="settingsOpen = true"
      >
        设置
      </button>
    </header>

    <StatusBar
      :sources="sources"
      :feishu-configured="Boolean(config?.feishu.app_secret_configured)"
      :live-status="liveStatus"
    />

    <main>
      <section class="task-toolbar">
        <div>
          <p class="eyebrow">TASKS</p>
          <h2>本机任务</h2>
        </div>
        <FilterTabs
          :active="activeFilter"
          :counts="counts"
          @change="activeFilter = $event"
        />
      </section>

      <p v-if="errorMessage" class="alert" role="alert">
        {{ errorMessage }}
      </p>
      <div v-if="loading" class="empty-state">正在读取任务状态…</div>
      <div v-else-if="visibleTasks.length" class="task-grid">
        <TaskCard
          v-for="task in visibleTasks"
          :key="task.thread_id"
          :task="task"
          :busy="busyTasks.has(task.thread_id)"
          @watch="watchTask(task, $event)"
          @stop="stopTaskWatch(task)"
          @details="selectedTask = task"
        />
      </div>
      <div v-else class="empty-state">
        <span class="empty-mark" aria-hidden="true">◎</span>
        <h3>当前筛选下没有任务</h3>
        <p>任务状态变化后会自动出现在这里。</p>
      </div>
    </main>

    <TaskDetails
      v-if="selectedTask"
      :task="selectedTask"
      @close="selectedTask = null"
    />

    <SettingsPanel
      v-if="settingsOpen && config"
      :initial-config="config"
      @saved="config = $event"
      @close="settingsOpen = false"
    />
  </div>
</template>
