<script setup lang="ts">
import {
  nextTick,
  onMounted,
  onUnmounted,
  ref,
} from "vue"

const props = defineProps<{
  x: number
  y: number
  disabled: boolean
}>()

const emit = defineEmits<{
  manualCompletion: []
  close: []
}>()

const viewportMargin = 8
const menu = ref<HTMLElement | null>(null)
const action = ref<HTMLButtonElement | null>(null)
const left = ref(props.x)
const top = ref(props.y)

function close(): void {
  emit("close")
}

function handlePointerDown(event: Event): void {
  if (
    event.target instanceof Node
    && menu.value?.contains(event.target)
  ) {
    return
  }
  close()
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    close()
  }
}

function updatePosition(): void {
  if (!menu.value) {
    return
  }
  const bounds = menu.value.getBoundingClientRect()
  left.value = Math.max(
    viewportMargin,
    Math.min(
      props.x,
      window.innerWidth - bounds.width - viewportMargin,
    ),
  )
  top.value = Math.max(
    viewportMargin,
    Math.min(
      props.y,
      window.innerHeight - bounds.height - viewportMargin,
    ),
  )
}

onMounted(() => {
  document.addEventListener("pointerdown", handlePointerDown)
  window.addEventListener("keydown", handleKeydown)
  window.addEventListener("scroll", close)
  window.addEventListener("resize", close)
  void nextTick(() => {
    updatePosition()
    action.value?.focus()
  })
})

onUnmounted(() => {
  document.removeEventListener("pointerdown", handlePointerDown)
  window.removeEventListener("keydown", handleKeydown)
  window.removeEventListener("scroll", close)
  window.removeEventListener("resize", close)
})
</script>

<template>
  <Teleport to="body">
    <section
      ref="menu"
      class="task-context-menu"
      role="menu"
      aria-label="任务操作"
      :style="{ left: `${left}px`, top: `${top}px` }"
    >
      <button
        ref="action"
        type="button"
        class="task-context-menu-item"
        role="menuitem"
        data-action="context-manual-completion"
        :disabled="disabled"
        @click="$emit('manualCompletion')"
      >
        标记本轮已结束
      </button>
    </section>
  </Teleport>
</template>
