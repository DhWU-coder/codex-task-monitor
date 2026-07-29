<script setup lang="ts">
import type { TaskSnapshot } from "../types"

defineProps<{
  task: TaskSnapshot
}>()

defineEmits<{
  close: []
}>()

function formatTime(value: string | null): string {
  if (!value) {
    return "—"
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value))
}
</script>

<template>
  <div class="dialog-backdrop" @click.self="$emit('close')">
    <section
      class="details-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="task-details-title"
    >
      <header class="dialog-header">
        <div>
          <p class="eyebrow">任务详情</p>
          <h2 id="task-details-title">{{ task.title }}</h2>
        </div>
        <button
          type="button"
          class="icon-button"
          aria-label="关闭任务详情"
          @click="$emit('close')"
        >
          ×
        </button>
      </header>

      <dl class="details-list">
        <div>
          <dt>任务 ID</dt>
          <dd>{{ task.thread_id }}</dd>
        </div>
        <div>
          <dt>轮次 ID</dt>
          <dd>{{ task.turn_id || "—" }}</dd>
        </div>
        <div>
          <dt>项目</dt>
          <dd>{{ task.project_name || "—" }}</dd>
        </div>
        <div>
          <dt>分支</dt>
          <dd>{{ task.branch || "—" }}</dd>
        </div>
        <div class="details-wide">
          <dt>工作目录</dt>
          <dd>{{ task.cwd || "—" }}</dd>
        </div>
        <div>
          <dt>开始时间</dt>
          <dd>{{ formatTime(task.started_at) }}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{{ formatTime(task.updated_at) }}</dd>
        </div>
      </dl>

      <section class="details-summary">
        <h3>最近摘要</h3>
        <p>{{ task.latest_summary || task.waiting_reason || "暂无摘要。" }}</p>
      </section>
      <section v-if="task.error_summary" class="details-error">
        <h3>错误摘要</h3>
        <p>{{ task.error_summary }}</p>
      </section>
    </section>
  </div>
</template>
