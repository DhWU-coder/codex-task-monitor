<script setup lang="ts">
import type { WatchMode } from "../types"

defineProps<{
  activeCount: number
  busy: boolean
}>()

defineEmits<{
  watch: [mode: WatchMode]
}>()
</script>

<template>
  <section
    class="current-filter-watch-actions"
    aria-label="当前筛选批量监控"
  >
    <span class="current-filter-watch-label">当前筛选</span>
    <button
      type="button"
      class="button button-primary"
      data-current-filter-watch="current_turn"
      :disabled="busy || activeCount === 0"
      @click="$emit('watch', 'current_turn')"
    >
      监控当前轮次
    </button>
    <button
      type="button"
      class="button button-secondary"
      data-current-filter-watch="persistent"
      :disabled="busy || activeCount === 0"
      @click="$emit('watch', 'persistent')"
    >
      持续监控
    </button>
  </section>
</template>
