import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  THEME_STORAGE_KEY,
  initializeTheme,
  setThemePreference,
  watchSystemTheme,
} from "../src/theme"

class FakeMediaQueryList {
  matches: boolean
  listeners = new Set<(event: MediaQueryListEvent) => void>()

  constructor(matches: boolean) {
    this.matches = matches
  }

  addEventListener(
    type: string,
    listener: (event: MediaQueryListEvent) => void,
  ): void {
    if (type === "change") {
      this.listeners.add(listener)
    }
  }

  removeEventListener(
    type: string,
    listener: (event: MediaQueryListEvent) => void,
  ): void {
    if (type === "change") {
      this.listeners.delete(listener)
    }
  }

  emit(matches: boolean): void {
    this.matches = matches
    const event = { matches } as MediaQueryListEvent
    for (const listener of this.listeners) {
      listener(event)
    }
  }
}

class FakeStorage implements Storage {
  private values = new Map<string, string>()

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

let mediaQuery: FakeMediaQueryList

function useSystemTheme(matches: boolean): void {
  mediaQuery = new FakeMediaQueryList(matches)
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => mediaQuery as unknown as MediaQueryList),
  })
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: new FakeStorage(),
  })
  window.localStorage.clear()
  delete document.documentElement.dataset.theme
  document.documentElement.style.colorScheme = ""
  useSystemTheme(false)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("浏览器主题管理", () => {
  it("没有手动偏好时跟随系统深色主题", () => {
    useSystemTheme(true)

    const theme = initializeTheme()

    expect(theme).toBe("dark")
    expect(document.documentElement.dataset.theme).toBe("dark")
    expect(document.documentElement.style.colorScheme).toBe("dark")
  })

  it("已保存的浅色主题优先于系统深色主题", () => {
    useSystemTheme(true)
    window.localStorage.setItem(THEME_STORAGE_KEY, "light")

    const theme = initializeTheme()

    expect(theme).toBe("light")
    expect(document.documentElement.dataset.theme).toBe("light")
  })

  it("无效存储值回退到系统主题", () => {
    useSystemTheme(true)
    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia")

    expect(initializeTheme()).toBe("dark")
  })

  it("手动选择会立即应用并保存主题", () => {
    setThemePreference("dark")

    expect(document.documentElement.dataset.theme).toBe("dark")
    expect(document.documentElement.style.colorScheme).toBe("dark")
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark")
  })

  it("存储写入失败时仍在当前页面应用主题", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("模拟存储不可用")
    })

    expect(() => setThemePreference("dark")).not.toThrow()
    expect(document.documentElement.dataset.theme).toBe("dark")
  })

  it("未手动选择时响应系统变化并支持停止监听", () => {
    const listener = vi.fn()
    const stop = watchSystemTheme(listener)

    expect(mediaQuery.listeners.size).toBe(1)
    mediaQuery.emit(true)
    expect(listener).toHaveBeenCalledWith("dark")
    expect(document.documentElement.dataset.theme).toBe("dark")

    stop()
    expect(mediaQuery.listeners.size).toBe(0)
  })

  it("已有手动选择时不监听系统变化", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light")

    const stop = watchSystemTheme(vi.fn())

    expect(mediaQuery.listeners.size).toBe(0)
    expect(stop).toBeTypeOf("function")
  })

  it("浏览器不支持主题查询时安全回退到浅色", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: undefined,
    })

    expect(initializeTheme()).toBe("light")
  })
})
