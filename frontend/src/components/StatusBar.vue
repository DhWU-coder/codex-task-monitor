<script setup lang="ts">
import type { SourceHealth } from "../types"

defineProps<{
  sources: Record<string, SourceHealth>
  feishuConfigured: boolean
  liveStatus: "connecting" | "connected" | "disconnected"
}>()

function stateClass(connected: boolean): string {
  return connected ? "is-online" : "is-offline"
}
</script>

<template>
  <section class="status-bar" aria-label="服务状态">
    <div class="status-item">
      <span
        class="status-dot"
        :class="stateClass(Boolean(sources.app_server?.connected))"
        aria-hidden="true"
      />
      <span>
        <strong>App Server</strong>
        {{ sources.app_server?.connected ? "已连接" : "未连接" }}
      </span>
    </div>
    <div class="status-item">
      <span
        class="status-dot"
        :class="stateClass(Boolean(sources.session_observer?.connected))"
        aria-hidden="true"
      />
      <span>
        <strong>会话观察</strong>
        {{ sources.session_observer?.connected ? "正常" : "异常" }}
      </span>
    </div>
    <div class="status-item">
      <span
        class="status-dot"
        :class="stateClass(feishuConfigured)"
        aria-hidden="true"
      />
      <span>
        <strong>飞书通知</strong>
        {{ feishuConfigured ? "已配置" : "待配置" }}
      </span>
    </div>
    <div class="status-item status-item-live">
      <span
        class="status-dot"
        :class="stateClass(liveStatus === 'connected')"
        aria-hidden="true"
      />
      <span>
        <strong>实时更新</strong>
        {{
          liveStatus === "connected"
            ? "已连接"
            : liveStatus === "connecting"
              ? "连接中"
              : "重连中"
        }}
      </span>
    </div>
  </section>
</template>
