import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

const styles = readFileSync("src/styles.css", "utf8")

describe("任务列表样式", () => {
  it("只在桌面横向布局压缩任务行最小高度", () => {
    expect(styles).toMatch(
      /\.task-card\s*\{[^}]*min-height:\s*100px;/s,
    )
    expect(styles).toMatch(
      /@media \(min-width: 961px\)\s*\{\s*\.task-card\s*\{\s*min-height:\s*84px;/s,
    )
  })
})
