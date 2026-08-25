import { createSSRApp } from 'vue'
import App from './App.vue'
import './styles/base.css'

export function createApp() {
  const app = createSSRApp(App)
  return { app }
}
