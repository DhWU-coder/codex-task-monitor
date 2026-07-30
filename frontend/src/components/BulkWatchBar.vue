<script setup lang="ts">
import type { WatchMode } from "../types"

defineProps<{
  selectedCount: number
  busy: boolean
}>()

defineEmits<{
  selectAll: []
  clearSelection: []
  watch: [mode: WatchMode]
  exit: []
}>()
</script>

<template>
  <section class="bulk-watch-bar" aria-label="批量监控操作">
    <p class="bulk-watch-summary">
      已选择 <strong>{{ selectedCount }}</strong> 项
    </p>
    <div class="bulk-watch-actions">
      <button
        type="button"
        class="button button-secondary"
        data-action="select-all"
        :disabled="busy"
        @click="$emit('selectAll')"
      >
        全选
      </button>
      <button
        type="button"
        class="button button-secondary"
        data-action="clear-selection"
        :disabled="busy"
        @click="$emit('clearSelection')"
      >
        清空选择
      </button>
      <span class="bulk-watch-divider" aria-hidden="true"></span>
      <button
        type="button"
        class="button button-primary"
        data-watch="current_turn"
        :disabled="busy || selectedCount === 0"
        @click="$emit('watch', 'current_turn')"
      >
        监控当前轮次
      </button>
      <button
        type="button"
        class="button button-secondary"
        data-watch="persistent"
        :disabled="busy || selectedCount === 0"
        @click="$emit('watch', 'persistent')"
      >
        持续监控
      </button>
      <button
        type="button"
        class="button button-quiet"
        data-action="exit-selection"
        :disabled="busy"
        @click="$emit('exit')"
      >
        退出选择
      </button>
    </div>
  </section>
</template>
