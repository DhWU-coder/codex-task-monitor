<script setup lang="ts">
export type TaskFilter =
  | "running"
  | "monitored"
  | "attention"
  | "recent"
  | "all"

defineProps<{
  active: TaskFilter
  counts: Record<TaskFilter, number>
}>()

defineEmits<{
  change: [filter: TaskFilter]
}>()

const tabs: Array<{ key: TaskFilter; label: string }> = [
  { key: "running", label: "运行中" },
  { key: "monitored", label: "监控中" },
  { key: "attention", label: "需处理" },
  { key: "recent", label: "最近结束" },
  { key: "all", label: "全部" },
]
</script>

<template>
  <nav class="filter-tabs" aria-label="任务筛选">
    <button
      v-for="tab in tabs"
      :key="tab.key"
      type="button"
      class="filter-tab"
      :class="{ 'is-active': active === tab.key }"
      :aria-current="active === tab.key ? 'page' : undefined"
      :data-filter="tab.key"
      @click="$emit('change', tab.key)"
    >
      {{ tab.label }}
      <span class="filter-count">{{ counts[tab.key] }}</span>
    </button>
  </nav>
</template>
