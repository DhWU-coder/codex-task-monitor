import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import BulkWatchBar from "../src/components/BulkWatchBar.vue"

describe("批量监控操作栏", () => {
  it("显示选择数量和完整操作", () => {
    const wrapper = mount(BulkWatchBar, {
      props: {
        selectedCount: 2,
        busy: false,
      },
    })

    expect(wrapper.text()).toContain("已选择 2 项")
    expect(wrapper.get("[data-action='select-all']").text()).toBe("全选")
    expect(wrapper.get("[data-action='clear-selection']").text()).toBe(
      "清空选择",
    )
    expect(wrapper.get("[data-watch='current_turn']").text()).toBe(
      "监控当前轮次",
    )
    expect(wrapper.get("[data-watch='persistent']").text()).toBe("持续监控")
    expect(wrapper.get("[data-action='exit-selection']").text()).toBe(
      "退出选择",
    )
  })

  it("点击操作时发出对应事件", async () => {
    const wrapper = mount(BulkWatchBar, {
      props: {
        selectedCount: 2,
        busy: false,
      },
    })

    await wrapper.get("[data-action='select-all']").trigger("click")
    await wrapper.get("[data-action='clear-selection']").trigger("click")
    await wrapper.get("[data-watch='current_turn']").trigger("click")
    await wrapper.get("[data-watch='persistent']").trigger("click")
    await wrapper.get("[data-action='exit-selection']").trigger("click")

    expect(wrapper.emitted("selectAll")).toHaveLength(1)
    expect(wrapper.emitted("clearSelection")).toHaveLength(1)
    expect(wrapper.emitted("watch")).toEqual([
      ["current_turn"],
      ["persistent"],
    ])
    expect(wrapper.emitted("exit")).toHaveLength(1)
  })

  it("无选择时禁用监控，忙碌时禁用全部操作", async () => {
    const wrapper = mount(BulkWatchBar, {
      props: {
        selectedCount: 0,
        busy: false,
      },
    })

    expect(
      wrapper.get("[data-watch='current_turn']").attributes("disabled"),
    ).toBeDefined()
    expect(
      wrapper.get("[data-watch='persistent']").attributes("disabled"),
    ).toBeDefined()
    expect(
      wrapper.get("[data-action='select-all']").attributes("disabled"),
    ).toBeUndefined()

    await wrapper.setProps({ selectedCount: 2, busy: true })

    for (const button of wrapper.findAll("button")) {
      expect(button.attributes("disabled")).toBeDefined()
    }
  })
})
