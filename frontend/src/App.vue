<script setup lang="ts">
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  watch,
} from "vue"

import {
  createTaskEventSource,
  getConfig,
  getHealth,
  getTasks,
  markManualCompletion,
  startWatch,
  stopWatch,
} from "./api"
import BulkWatchBar from "./components/BulkWatchBar.vue"
import ConfirmDialog from "./components/ConfirmDialog.vue"
import CurrentFilterWatchActions from "./components/CurrentFilterWatchActions.vue"
import FilterTabs, {
  type TaskFilter,
} from "./components/FilterTabs.vue"
import SettingsPanel from "./components/SettingsPanel.vue"
import StatusBar from "./components/StatusBar.vue"
import TaskCard from "./components/TaskCard.vue"
import TaskContextMenu from "./components/TaskContextMenu.vue"
import TaskDetails from "./components/TaskDetails.vue"
import {
  initializeTheme,
  setThemePreference,
  watchSystemTheme,
  type Theme,
} from "./theme"
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
const pendingManualCompletionTask = ref<TaskSnapshot | null>(null)
const settingsOpen = ref(false)
const loading = ref(true)
const errorMessage = ref("")
const busyTasks = ref(new Set<string>())
const selectionMode = ref(false)
const selectedTaskIds = ref(new Set<string>())
const bulkWatching = ref(false)
const taskContextMenu = ref<{
  task: TaskSnapshot
  x: number
  y: number
} | null>(null)
const theme = ref<Theme>(initializeTheme())
const liveStatus = ref<"connecting" | "connected" | "disconnected">(
  "connecting",
)

let eventSource: EventSource | null = null
let reconnectTimer: number | null = null
let reconnectAttempt = 0
let mounted = true
let stopThemeWatch: (() => void) | null = null

const activeStatuses = new Set([
  "running",
  "waiting_approval",
  "waiting_input",
])
const attentionStatuses = new Set(["waiting_approval", "waiting_input"])
const terminalStatuses = new Set([
  "completed",
  "failed",
  "interrupted",
  "manually_completed",
])

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

const visibleActiveTasks = computed(() =>
  visibleTasks.value.filter((task) => activeStatuses.has(task.status)),
)

function enterSelectionMode(): void {
  taskContextMenu.value = null
  selectionMode.value = true
}

function exitSelectionMode(): void {
  selectedTaskIds.value = new Set()
  selectionMode.value = false
}

function toggleTaskSelection(threadId: string): void {
  const task = tasks.value.find((item) => item.thread_id === threadId)
  if (!task || !activeStatuses.has(task.status)) {
    return
  }
  const next = new Set(selectedTaskIds.value)
  if (next.has(threadId)) {
    next.delete(threadId)
  } else {
    next.add(threadId)
  }
  selectedTaskIds.value = next
}

function selectAllVisible(): void {
  const next = new Set(selectedTaskIds.value)
  for (const task of visibleTasks.value) {
    if (activeStatuses.has(task.status)) {
      next.add(task.thread_id)
    }
  }
  selectedTaskIds.value = next
}

function clearSelection(): void {
  selectedTaskIds.value = new Set()
}

function openTaskContextMenu(
  task: TaskSnapshot,
  position: { x: number; y: number },
): void {
  if (
    selectionMode.value
    || !activeStatuses.has(task.status)
  ) {
    return
  }
  taskContextMenu.value = {
    task,
    ...position,
  }
}

function startManualCompletionFromMenu(): void {
  const context = taskContextMenu.value
  taskContextMenu.value = null
  if (!context) {
    return
  }
  const latestTask = tasks.value.find(
    (task) => task.thread_id === context.task.thread_id,
  )
  if (latestTask && activeStatuses.has(latestTask.status)) {
    pendingManualCompletionTask.value = latestTask
  }
}

function targetWatchMode(
  task: TaskSnapshot,
  requestedMode: WatchMode,
): WatchMode {
  if (
    requestedMode === "current_turn"
    && task.monitored
    && task.watch_mode === "persistent"
  ) {
    return "persistent"
  }
  return requestedMode
}

async function executeWatchGroup(
  taskRows: TaskSnapshot[],
  requestedMode: WatchMode,
): Promise<{
  succeededIds: Set<string>
  failureMessages: string[]
}> {
  const requestedIds = new Set(
    taskRows.map((task) => task.thread_id),
  )
  const activeTasks = tasks.value.filter(
    (task) =>
      requestedIds.has(task.thread_id)
      && activeStatuses.has(task.status),
  )

  for (const task of activeTasks) {
    setBusy(task.thread_id, true)
  }

  try {
    const results = await Promise.allSettled(
      activeTasks.map(async (task) => {
        const mode = targetWatchMode(task, requestedMode)
        if (task.monitored && task.watch_mode === mode) {
          return { threadId: task.thread_id, mode }
        }
        await startWatch(task.thread_id, mode)
        return { threadId: task.thread_id, mode }
      }),
    )

    const succeededIds = new Set<string>()
    const failureMessages: string[] = []
    for (const [index, result] of results.entries()) {
      const task = activeTasks[index]
      if (result.status === "fulfilled") {
        succeededIds.add(task.thread_id)
        replaceTask(task.thread_id, {
          monitored: true,
          watch_mode: result.value.mode,
        })
      } else {
        failureMessages.push(
          result.reason instanceof Error
            ? result.reason.message
            : "未知错误",
        )
      }
    }

    return { succeededIds, failureMessages }
  } finally {
    for (const task of activeTasks) {
      setBusy(task.thread_id, false)
    }
  }
}

async function bulkWatchTasks(requestedMode: WatchMode): Promise<void> {
  if (bulkWatching.value) {
    return
  }
  const selectedTasks = tasks.value.filter(
    (task) =>
      selectedTaskIds.value.has(task.thread_id)
      && activeStatuses.has(task.status),
  )
  if (!selectedTasks.length) {
    return
  }

  bulkWatching.value = true
  errorMessage.value = ""

  try {
    const { succeededIds, failureMessages } =
      await executeWatchGroup(selectedTasks, requestedMode)

    selectedTaskIds.value = new Set(
      [...selectedTaskIds.value].filter(
        (threadId) => !succeededIds.has(threadId),
      ),
    )
    if (failureMessages.length) {
      errorMessage.value =
        `${failureMessages.length} 个任务启动监控失败：`
        + failureMessages[0]
    } else {
      exitSelectionMode()
    }
  } finally {
    bulkWatching.value = false
  }
}

async function watchVisibleTasks(
  requestedMode: WatchMode,
): Promise<void> {
  if (bulkWatching.value || loading.value) {
    return
  }
  const taskRows = [...visibleActiveTasks.value]
  if (!taskRows.length) {
    return
  }

  bulkWatching.value = true
  errorMessage.value = ""

  try {
    const { failureMessages } = await executeWatchGroup(
      taskRows,
      requestedMode,
    )
    if (failureMessages.length) {
      errorMessage.value =
        `${failureMessages.length} 个任务启动监控失败：`
        + failureMessages[0]
    }
  } finally {
    bulkWatching.value = false
  }
}

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

async function completeTaskManually(task: TaskSnapshot): Promise<void> {
  if (!activeStatuses.has(task.status)) {
    return
  }
  setBusy(task.thread_id, true)
  errorMessage.value = ""
  try {
    const updated = await markManualCompletion(task.thread_id)
    replaceTask(task.thread_id, updated)
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "标记本轮已结束失败"
  } finally {
    setBusy(task.thread_id, false)
  }
}

function confirmManualCompletion(): void {
  const task = pendingManualCompletionTask.value
  pendingManualCompletionTask.value = null
  if (task) {
    void completeTaskManually(task)
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

function toggleTheme(): void {
  const nextTheme = theme.value === "light" ? "dark" : "light"
  stopThemeWatch?.()
  stopThemeWatch = null
  setThemePreference(nextTheme)
  theme.value = nextTheme
}

watch(tasks, (taskRows) => {
  const activeTaskIds = new Set(
    taskRows
      .filter((task) => activeStatuses.has(task.status))
      .map((task) => task.thread_id),
  )
  const next = new Set(
    [...selectedTaskIds.value].filter((threadId) =>
      activeTaskIds.has(threadId),
    ),
  )
  if (next.size !== selectedTaskIds.value.size) {
    selectedTaskIds.value = next
  }
  if (
    pendingManualCompletionTask.value
    && !taskRows.some(
      (task) =>
        task.thread_id === pendingManualCompletionTask.value?.thread_id
        && activeStatuses.has(task.status),
    )
  ) {
    pendingManualCompletionTask.value = null
  }
  if (
    taskContextMenu.value
    && !taskRows.some(
      (task) =>
        task.thread_id === taskContextMenu.value?.task.thread_id
        && activeStatuses.has(task.status),
    )
  ) {
    taskContextMenu.value = null
  }
})

onMounted(async () => {
  stopThemeWatch = watchSystemTheme((nextTheme) => {
    theme.value = nextTheme
  })
  await loadInitial()
  connectEvents()
})

onUnmounted(() => {
  mounted = false
  stopThemeWatch?.()
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
      <div class="header-actions">
        <button
          type="button"
          class="button button-secondary theme-toggle"
          data-action="theme-toggle"
          :aria-label="
            theme === 'light' ? '切换到深色主题' : '切换到浅色主题'
          "
          :aria-pressed="theme === 'dark'"
          :title="
            theme === 'light' ? '切换到深色主题' : '切换到浅色主题'
          "
          @click="toggleTheme"
        >
          <span aria-hidden="true">{{ theme === "light" ? "☾" : "☀" }}</span>
        </button>
        <button
          type="button"
          class="button button-secondary settings-button"
          @click="settingsOpen = true"
        >
          设置
        </button>
      </div>
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
        <div class="task-toolbar-controls">
          <CurrentFilterWatchActions
            v-if="!selectionMode"
            :active-count="visibleActiveTasks.length"
            :busy="bulkWatching || loading"
            @watch="watchVisibleTasks"
          />
          <FilterTabs
            :active="activeFilter"
            :counts="counts"
            @change="activeFilter = $event"
          />
          <button
            v-if="!selectionMode"
            type="button"
            class="button button-secondary"
            data-action="enter-selection"
            :disabled="bulkWatching"
            @click="enterSelectionMode"
          >
            选择
          </button>
        </div>
      </section>

      <p v-if="errorMessage" class="alert" role="alert">
        {{ errorMessage }}
      </p>
      <BulkWatchBar
        v-if="selectionMode"
        :selected-count="selectedTaskIds.size"
        :busy="bulkWatching"
        @select-all="selectAllVisible"
        @clear-selection="clearSelection"
        @watch="bulkWatchTasks"
        @exit="exitSelectionMode"
      />
      <div v-if="loading" class="empty-state">正在读取任务状态…</div>
      <div
        v-else-if="visibleTasks.length"
        class="task-list"
        data-task-list
      >
        <TaskCard
          v-for="task in visibleTasks"
          :key="task.thread_id"
          :task="task"
          :busy="busyTasks.has(task.thread_id)"
          :selection-mode="selectionMode"
          :selected="selectedTaskIds.has(task.thread_id)"
          :selectable="activeStatuses.has(task.status)"
          @watch="watchTask(task, $event)"
          @stop="stopTaskWatch(task)"
          @details="selectedTask = task"
          @toggle-selection="toggleTaskSelection(task.thread_id)"
          @open-context-menu="openTaskContextMenu(task, $event)"
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

    <TaskContextMenu
      v-if="taskContextMenu"
      :key="
        `${taskContextMenu.task.thread_id}:`
        + `${taskContextMenu.x}:${taskContextMenu.y}`
      "
      :x="taskContextMenu.x"
      :y="taskContextMenu.y"
      :disabled="busyTasks.has(taskContextMenu.task.thread_id)"
      @manual-completion="startManualCompletionFromMenu"
      @close="taskContextMenu = null"
    />

    <ConfirmDialog
      v-if="pendingManualCompletionTask"
      title="标记本轮已结束"
      message="确认后会从当前运行列表移除；同一轮后续更新将被忽略，任务下一轮启动时仍会重新出现。"
      confirm-label="确认结束"
      tone="danger"
      @confirm="confirmManualCompletion"
      @cancel="pendingManualCompletionTask = null"
    />
  </div>
</template>
