<script setup lang="ts">
import {
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  useId,
} from "vue"

withDefaults(
  defineProps<{
    title: string
    message: string
    confirmLabel: string
    tone?: "default" | "danger"
  }>(),
  {
    tone: "default",
  },
)

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const titleId = useId()
const messageId = useId()
const closeButton = ref<HTMLButtonElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
const confirmButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null

function cancel(): void {
  emit("cancel")
}

function confirm(): void {
  emit("confirm")
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    cancel()
    return
  }
  if (event.key !== "Tab") {
    return
  }
  const focusable = [
    closeButton.value,
    cancelButton.value,
    confirmButton.value,
  ].filter((item): item is HTMLButtonElement => item !== null)
  const first = focusable[0]
  const last = focusable.at(-1)
  if (!first || !last) {
    return
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  previousFocus =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
  window.addEventListener("keydown", handleKeydown)
  void nextTick(() => {
    cancelButton.value?.focus()
  })
})

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown)
  previousFocus?.focus()
})
</script>

<template>
  <Teleport to="body">
    <div class="confirm-backdrop" @click.self="cancel">
      <section
        class="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="messageId"
      >
        <button
          ref="closeButton"
          type="button"
          class="icon-button confirm-close"
          aria-label="关闭确认弹窗"
          data-action="confirm-dialog-close"
          @click="cancel"
        >
          ×
        </button>
        <div
          class="confirm-icon"
          :data-tone="tone"
          aria-hidden="true"
        >
          {{ tone === "danger" ? "!" : "✓" }}
        </div>
        <div class="confirm-copy">
          <h2 :id="titleId">{{ title }}</h2>
          <p :id="messageId">{{ message }}</p>
        </div>
        <footer class="confirm-actions">
          <button
            ref="cancelButton"
            type="button"
            class="button button-secondary"
            data-action="confirm-dialog-cancel"
            @click="cancel"
          >
            取消
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="button"
            :class="
              tone === 'danger' ? 'button-danger' : 'button-primary'
            "
            data-action="confirm-dialog-confirm"
            @click="confirm"
          >
            {{ confirmLabel }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
