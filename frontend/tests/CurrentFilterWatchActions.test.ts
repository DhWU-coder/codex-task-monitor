import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import CurrentFilterWatchActions from "../src/components/CurrentFilterWatchActions.vue"

describe("当前筛选批量监控操作", () => {
  it("显示操作标题和两个监控按钮", () => {
    const wrapper = mount(CurrentFilterWatchActions, {
      props: {
        activeCount: 2,
        busy: false,
      },
    })

    expect(wrapper.text()).toContain("当前筛选")
    expect(
      wrapper.get("[data-current-filter-watch='current_turn']").text(),
    ).toBe("监控当前轮次")
    expect(
      wrapper.get("[data-current-filter-watch='persistent']").text(),
    ).toBe("持续监控")
  })

  it("点击按钮时发出对应的监控模式", async () => {
    const wrapper = mount(CurrentFilterWatchActions, {
      props: {
        activeCount: 2,
        busy: false,
      },
    })

    await wrapper
      .get("[data-current-filter-watch='current_turn']")
      .trigger("click")
    await wrapper
      .get("[data-current-filter-watch='persistent']")
      .trigger("click")

    expect(wrapper.emitted("watch")).toEqual([
      ["current_turn"],
      ["persistent"],
    ])
  })

  it("没有活动任务时禁用两个按钮", () => {
    const wrapper = mount(CurrentFilterWatchActions, {
      props: {
        activeCount: 0,
        busy: false,
      },
    })

    for (const button of wrapper.findAll("button")) {
      expect(button.attributes("disabled")).toBeDefined()
    }
  })

  it("批量操作忙碌时禁用两个按钮", () => {
    const wrapper = mount(CurrentFilterWatchActions, {
      props: {
        activeCount: 2,
        busy: true,
      },
    })

    for (const button of wrapper.findAll("button")) {
      expect(button.attributes("disabled")).toBeDefined()
    }
  })
})
