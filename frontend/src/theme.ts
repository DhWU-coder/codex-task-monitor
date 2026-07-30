export type Theme = "light" | "dark"

export const THEME_STORAGE_KEY = "codex-task-monitor-theme"

const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)"

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return stored === "light" || stored === "dark" ? stored : null
  } catch {
    return null
  }
}

function readSystemTheme(): Theme {
  if (typeof window.matchMedia !== "function") {
    return "light"
  }
  return window.matchMedia(SYSTEM_THEME_QUERY).matches ? "dark" : "light"
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

export function initializeTheme(): Theme {
  const theme = readStoredTheme() ?? readSystemTheme()
  applyTheme(theme)
  return theme
}

export function setThemePreference(theme: Theme): void {
  applyTheme(theme)
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    return
  }
}

export function watchSystemTheme(
  listener: (theme: Theme) => void,
): () => void {
  if (
    readStoredTheme() !== null ||
    typeof window.matchMedia !== "function"
  ) {
    return () => undefined
  }
  const mediaQuery = window.matchMedia(SYSTEM_THEME_QUERY)
  const handleChange = (event: MediaQueryListEvent): void => {
    const theme = event.matches ? "dark" : "light"
    applyTheme(theme)
    listener(theme)
  }
  mediaQuery.addEventListener("change", handleChange)
  return () => mediaQuery.removeEventListener("change", handleChange)
}
