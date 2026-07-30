<script setup lang="ts">
import type { TaskSnapshot, TaskStatus, WatchMode } from "../types"

const props = defineProps<{
  task: TaskSnapshot
  busy: boolean
  selectionMode: boolean
  selected: boolean
  selectable: boolean
}>()

const emit = defineEmits<{
  watch: [mode: WatchMode]
  stop: []
  details: []
  toggleSelection: []
  openContextMenu: [position: { x: number; y: number }]
}>()

const statusLabels: Record<TaskStatus, string> = {
  running: "运行中",
  waiting_approval: "等待审批",
  waiting_input: "等待输入",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  manually_completed: "手动结束",
  unknown: "状态未知",
  source_error: "数据源异常",
}

function isActive(task: TaskSnapshot): boolean {
  return ["running", "waiting_approval", "waiting_input"].includes(task.status)
}

function formatElapsed(task: TaskSnapshot): string {
  if (!task.started_at) {
    return "时长未知"
  }
  const start = new Date(task.started_at).getTime()
  const end = task.completed_at
    ? new Date(task.completed_at).getTime()
    : Date.now()
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return `${minutes} 分钟`
  }
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分`
}

function watchLabel(mode: WatchMode | null): string {
  return mode === "persistent" ? "持续监控中" : "当前轮监控中"
}

function handleContextMenu(event: MouseEvent): void {
  if (props.selectionMode || !props.selectable) {
    return
  }
  event.preventDefault()
  emit("openContextMenu", {
    x: event.clientX,
    y: event.clientY,
  })
}
</script>

<template>
  <article
    class="task-card"
    :data-status="task.status"
    :data-selected="selected || undefined"
    @contextmenu="handleContextMenu"
  >
    <section class="task-row-identity" data-task-identity>
      <header class="task-card-header" data-task-primary>
        <label
          v-if="selectionMode && selectable"
          class="task-selection"
        >
          <input
            type="checkbox"
            :checked="selected"
            :data-task-selection="task.thread_id"
            :aria-label="`选择任务：${task.title || '未命名任务'}`"
            :disabled="busy"
            @change="$emit('toggleSelection')"
          />
          <span aria-hidden="true"></span>
        </label>
        <span class="status-badge" :data-status="task.status">
          {{ statusLabels[task.status] }}
        </span>
        <h2>{{ task.title || "未命名任务" }}</h2>
        <span v-if="task.monitored" class="watch-badge">
          {{ watchLabel(task.watch_mode) }}
        </span>
      </header>
      <p v-if="task.waiting_reason" class="task-attention">
        {{ task.waiting_reason }}
      </p>
    </section>

    <dl class="task-row-meta" data-task-meta>
      <div>
        <dt>项目</dt>
        <dd>{{ task.project_name || "未识别" }}</dd>
      </div>
      <div>
        <dt>分支</dt>
        <dd>{{ task.branch || "无分支信息" }}</dd>
      </div>
      <div>
        <dt>运行时长</dt>
        <dd>{{ formatElapsed(task) }}</dd>
      </div>
    </dl>

    <footer class="task-row-actions" data-task-actions>
      <template v-if="isActive(props.task) && !selectionMode">
        <button
          v-if="task.monitored"
          type="button"
          class="button button-secondary"
          :disabled="busy"
          data-action="stop"
          @click="$emit('stop')"
        >
          停止监控
        </button>
        <template v-else>
          <button
            type="button"
            class="button button-primary"
            :disabled="busy"
            data-watch="current_turn"
            @click="$emit('watch', 'current_turn')"
          >
            监控当前轮次
          </button>
          <button
            type="button"
            class="button button-secondary"
            :disabled="busy"
            data-watch="persistent"
            @click="$emit('watch', 'persistent')"
          >
            持续监控
          </button>
        </template>
      </template>
      <button
        type="button"
        class="button button-quiet"
        data-action="details"
        @click="$emit('details')"
      >
        查看详情
      </button>
    </footer>
  </article>
</template>
