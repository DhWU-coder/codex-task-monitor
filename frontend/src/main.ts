import { createApp } from "vue"

import App from "./App.vue"
import { initializeTheme } from "./theme"
import "./styles.css"

initializeTheme()
createApp(App).mount("#app")
