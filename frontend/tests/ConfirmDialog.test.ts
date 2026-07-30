import { mount, type VueWrapper } from "@vue/test-utils"
import { afterEach, describe, expect, it } from "vitest"

import ConfirmDialog from "../src/components/ConfirmDialog.vue"

const wrappers: VueWrapper[] = []

function renderDialog(
  tone: "default" | "danger" = "default",
): VueWrapper {
  const wrapper = mount(ConfirmDialog, {
    attachTo: document.body,
    props: {
      title: "标记本轮已结束",
      message: "同一轮后续更新将被忽略。",
      confirmLabel: "确认结束",
      tone,
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) {
    wrapper.unmount()
  }
})

describe("确认弹窗", () => {
  it("危险操作使用主题化警示样式", () => {
    renderDialog("danger")

    const dialog = document.querySelector("[role='alertdialog']")
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    )

    expect(dialog?.textContent).toContain("标记本轮已结束")
    expect(dialog?.textContent).toContain("同一轮后续更新将被忽略。")
    expect(confirmButton?.classList.contains("button-danger")).toBe(true)
    expect(dialog?.querySelector(".confirm-icon")).not.toBeNull()
  })

  it("普通操作使用主按钮样式", () => {
    renderDialog()

    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    )

    expect(confirmButton?.classList.contains("button-primary")).toBe(true)
    expect(confirmButton?.classList.contains("button-danger")).toBe(false)
  })

  it("确认、取消和关闭按钮发出对应事件", async () => {
    const wrapper = renderDialog()
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    ) as HTMLButtonElement
    const cancelButton = document.querySelector(
      "[data-action='confirm-dialog-cancel']",
    ) as HTMLButtonElement
    const closeButton = document.querySelector(
      "[data-action='confirm-dialog-close']",
    ) as HTMLButtonElement

    confirmButton.click()
    cancelButton.click()
    closeButton.click()
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted("confirm")).toHaveLength(1)
    expect(wrapper.emitted("cancel")).toHaveLength(2)
  })

  it("点击遮罩或按下 Esc 时取消", async () => {
    const wrapper = renderDialog()
    const backdrop = document.querySelector(
      ".confirm-backdrop",
    ) as HTMLDivElement

    backdrop.click()
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted("cancel")).toHaveLength(2)
  })

  it("限制弹窗焦点并在关闭后恢复原焦点", async () => {
    const trigger = document.createElement("button")
    document.body.append(trigger)
    trigger.focus()

    const wrapper = renderDialog()
    await wrapper.vm.$nextTick()
    const closeButton = document.querySelector(
      "[data-action='confirm-dialog-close']",
    ) as HTMLButtonElement
    const cancelButton = document.querySelector(
      "[data-action='confirm-dialog-cancel']",
    ) as HTMLButtonElement
    const confirmButton = document.querySelector(
      "[data-action='confirm-dialog-confirm']",
    ) as HTMLButtonElement

    expect(document.activeElement).toBe(cancelButton)

    confirmButton.focus()
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(document.activeElement).toBe(closeButton)

    closeButton.focus()
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      }),
    )
    expect(document.activeElement).toBe(confirmButton)

    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })
})
