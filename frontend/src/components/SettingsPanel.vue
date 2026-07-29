<script setup lang="ts">
import { reactive, ref } from "vue"

import { sendTestNotification, updateConfig } from "../api"
import type { PublicConfig } from "../types"

const props = defineProps<{
  initialConfig: PublicConfig
}>()

const emit = defineEmits<{
  close: []
  saved: [config: PublicConfig]
}>()

const form = reactive({
  server: { ...props.initialConfig.server },
  codex: { ...props.initialConfig.codex },
  feishu: {
    app_id: props.initialConfig.feishu.app_id,
    app_secret: "",
    receive_id: props.initialConfig.feishu.receive_id,
    receive_id_type: props.initialConfig.feishu.receive_id_type,
  },
  notifications: { ...props.initialConfig.notifications },
})

const clearSecret = ref(false)
const saving = ref(false)
const testing = ref(false)
const errorMessage = ref("")
const successMessage = ref("")
const restartRequired = ref(false)

async function save(): Promise<void> {
  saving.value = true
  errorMessage.value = ""
  successMessage.value = ""
  try {
    const updated = await updateConfig({
      server: {
        ...form.server,
        port: Number(form.server.port),
      },
      codex: {
        ...form.codex,
        refresh_interval_seconds: Number(
          form.codex.refresh_interval_seconds,
        ),
        reconcile_interval_seconds: Number(
          form.codex.reconcile_interval_seconds,
        ),
        recent_completed_hours: Number(
          form.codex.recent_completed_hours,
        ),
      },
      feishu: {
        ...form.feishu,
        clear_app_secret: clearSecret.value,
      },
      notifications: {
        ...form.notifications,
        summary_max_length: Number(
          form.notifications.summary_max_length,
        ),
      },
    })
    restartRequired.value = Boolean(updated.restart_required)
    successMessage.value = "配置已保存。"
    form.feishu.app_secret = ""
    clearSecret.value = false
    emit("saved", updated)
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "保存配置失败"
  } finally {
    saving.value = false
  }
}

async function testNotification(): Promise<void> {
  if (!window.confirm("确认使用当前已保存配置发送一条飞书测试消息？")) {
    return
  }
  testing.value = true
  errorMessage.value = ""
  successMessage.value = ""
  try {
    await sendTestNotification()
    successMessage.value = "测试消息已发送。"
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "测试消息发送失败"
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="dialog-backdrop" @click.self="emit('close')">
    <section
      class="settings-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <header class="dialog-header">
        <div>
          <p class="eyebrow">CONFIGURATION</p>
          <h2 id="settings-title">监控器设置</h2>
        </div>
        <button
          type="button"
          class="icon-button"
          aria-label="关闭设置"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <form @submit.prevent="save">
        <fieldset class="settings-section">
          <legend>本地服务</legend>
          <div class="form-grid">
            <label>
              <span>监听地址</span>
              <select v-model="form.server.host" aria-label="监听地址">
                <option value="127.0.0.1">127.0.0.1</option>
                <option value="localhost">localhost</option>
                <option value="::1">::1</option>
              </select>
            </label>
            <label>
              <span>端口</span>
              <input
                v-model.number="form.server.port"
                aria-label="端口"
                type="number"
                min="1024"
                max="65535"
                required
              />
            </label>
          </div>
        </fieldset>

        <fieldset class="settings-section">
          <legend>Codex 数据源</legend>
          <div class="form-grid">
            <label class="form-wide">
              <span>Codex 命令</span>
              <input
                v-model="form.codex.command"
                aria-label="Codex 命令"
                autocomplete="off"
                required
              />
            </label>
            <label>
              <span>刷新间隔（秒）</span>
              <input
                v-model.number="form.codex.refresh_interval_seconds"
                aria-label="刷新间隔"
                type="number"
                min="0.1"
                max="60"
                step="0.1"
                required
              />
            </label>
            <label>
              <span>最近任务时限（小时）</span>
              <input
                v-model.number="form.codex.recent_completed_hours"
                aria-label="最近任务时限"
                type="number"
                min="1"
                max="720"
                required
              />
            </label>
          </div>
        </fieldset>

        <fieldset class="settings-section">
          <legend>飞书自建应用</legend>
          <div class="form-grid">
            <label>
              <span>App ID</span>
              <input
                v-model="form.feishu.app_id"
                aria-label="飞书 App ID"
                autocomplete="off"
              />
            </label>
            <label>
              <span>
                App Secret
                <small v-if="initialConfig.feishu.app_secret_configured">
                  密钥已配置
                </small>
              </span>
              <input
                v-model="form.feishu.app_secret"
                aria-label="飞书 App Secret"
                type="password"
                autocomplete="new-password"
                placeholder="留空则保留已保存密钥"
              />
            </label>
            <label>
              <span>接收人 ID</span>
              <input
                v-model="form.feishu.receive_id"
                aria-label="飞书接收人 ID"
                autocomplete="off"
              />
            </label>
            <label>
              <span>接收人 ID 类型</span>
              <select
                v-model="form.feishu.receive_id_type"
                aria-label="飞书接收人 ID 类型"
              >
                <option value="open_id">open_id</option>
                <option value="union_id">union_id</option>
                <option value="user_id">user_id</option>
                <option value="email">email</option>
              </select>
            </label>
          </div>
          <label class="checkbox-row danger-option">
            <input
              v-model="clearSecret"
              type="checkbox"
              aria-label="清除已保存密钥"
            />
            <span>清除已保存的 App Secret</span>
          </label>
        </fieldset>

        <fieldset class="settings-section">
          <legend>通知事件</legend>
          <div class="checkbox-grid">
            <label class="checkbox-row">
              <input v-model="form.notifications.enabled" type="checkbox" />
              <span>启用自动通知</span>
            </label>
            <label class="checkbox-row">
              <input
                v-model="form.notifications.notify_completed"
                type="checkbox"
              />
              <span>任务完成</span>
            </label>
            <label class="checkbox-row">
              <input
                v-model="form.notifications.notify_failed"
                type="checkbox"
              />
              <span>任务失败</span>
            </label>
            <label class="checkbox-row">
              <input
                v-model="form.notifications.notify_interrupted"
                type="checkbox"
              />
              <span>任务中断</span>
            </label>
            <label class="checkbox-row">
              <input
                v-model="form.notifications.notify_waiting_input"
                type="checkbox"
              />
              <span>等待输入</span>
            </label>
            <label class="checkbox-row">
              <input
                v-model="form.notifications.notify_waiting_approval"
                type="checkbox"
              />
              <span>等待审批</span>
            </label>
          </div>
        </fieldset>

        <p v-if="errorMessage" class="alert" role="alert">
          {{ errorMessage }}
        </p>
        <p v-if="successMessage" class="success-message" role="status">
          {{ successMessage }}
        </p>
        <p v-if="restartRequired" class="restart-message">
          地址或端口已变更，请执行
          <code>codex-task-monitor restart</code>
          后生效。
        </p>

        <footer class="settings-actions">
          <button
            type="button"
            class="button button-secondary"
            :disabled="testing"
            data-action="test-notification"
            @click="testNotification"
          >
            {{ testing ? "发送中…" : "发送测试消息" }}
          </button>
          <button
            type="submit"
            class="button button-primary"
            :disabled="saving"
          >
            {{ saving ? "保存中…" : "保存配置" }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>
