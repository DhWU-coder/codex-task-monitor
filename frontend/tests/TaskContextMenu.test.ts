import {
  flushPromises,
  mount,
  type VueWrapper,
} from "@vue/test-utils"
import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest"

import TaskContextMenu from "../src/components/TaskContextMenu.vue"

const wrappers: VueWrapper[] = []

function renderMenu(
  props: {
    x?: number
    y?: number
    disabled?: boolean
  } = {},
): VueWrapper {
  const wrapper = mount(TaskContextMenu, {
    attachTo: document.body,
    props: {
      x: props.x ?? 40,
      y: props.y ?? 60,
      disabled: props.disabled ?? false,
    },
    global: {
      stubs: { teleport: true },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) {
    wrapper.unmount()
  }
  vi.restoreAllMocks()
})

describe("任务右键菜单", () => {
  it("展示唯一的手动结束操作并发出事件", async () => {
    const wrapper = renderMenu()
    const action = wrapper.get(
      "[data-action='context-manual-completion']",
    )

    expect(wrapper.get("[role='menu']").exists()).toBe(true)
    expect(action.text()).toBe("标记本轮已结束")

    await action.trigger("click")

    expect(wrapper.emitted("manualCompletion")).toHaveLength(1)
  })

  it("忙碌时禁用操作且不发出事件", async () => {
    const wrapper = renderMenu({ disabled: true })
    const action = wrapper.get(
      "[data-action='context-manual-completion']",
    )

    expect(action.attributes("disabled")).toBeDefined()

    await action.trigger("click")

    expect(wrapper.emitted("manualCompletion")).toBeUndefined()
  })

  it("获得焦点并响应外部指针和全局关闭事件", async () => {
    const removeWindowListener = vi.spyOn(
      window,
      "removeEventListener",
    )
    const removeDocumentListener = vi.spyOn(
      document,
      "removeEventListener",
    )
    const wrapper = renderMenu()
    await flushPromises()
    const menu = wrapper.get("[role='menu']")
    const action = wrapper.get(
      "[data-action='context-manual-completion']",
    )

    expect(document.activeElement).toBe(action.element)

    await menu.trigger("pointerdown")
    expect(wrapper.emitted("close")).toBeUndefined()

    document.body.dispatchEvent(
      new Event("pointerdown", { bubbles: true }),
    )
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))
    window.dispatchEvent(new Event("scroll"))
    window.dispatchEvent(new Event("resize"))

    expect(wrapper.emitted("close")).toHaveLength(4)

    wrapper.unmount()
    wrappers.splice(wrappers.indexOf(wrapper), 1)
    expect(removeDocumentListener).toHaveBeenCalledWith(
      "pointerdown",
      expect.any(Function),
    )
    expect(removeWindowListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function),
    )
    expect(removeWindowListener).toHaveBeenCalledWith(
      "resize",
      expect.any(Function),
    )
  })

  it("将靠近右下角的坐标限制在视口内", async () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(300)
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(200)
    vi.spyOn(
      HTMLElement.prototype,
      "getBoundingClientRect",
    ).mockReturnValue({
      width: 180,
      height: 100,
      top: 0,
      right: 180,
      bottom: 100,
      left: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    const wrapper = renderMenu({ x: 290, y: 190 })
    await flushPromises()
    const menu = wrapper.get("[role='menu']")

    expect(menu.attributes("style")).toContain("left: 112px")
    expect(menu.attributes("style")).toContain("top: 92px")
  })
})
