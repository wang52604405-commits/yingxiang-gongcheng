import { createSSRApp } from 'vue'
import App from './App.vue'
import './styles/base.css'
import './styles/ui-polish.css'
import { initializeTheme } from '@/services/theme'

export function createApp() {
  initializeTheme()
  const app = createSSRApp(App)
  return { app }
}
