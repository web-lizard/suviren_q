import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

const app = createApp(App)

app.config.errorHandler = (error, _instance, info) => {
  globalThis.__BOOK_WUNDERWAFFE_ERROR__ = {
    message: error?.message || String(error),
    stack: error?.stack || '',
    info,
  }
  console.error('[BOOK WUNDERWAFFE Studio]', info, error)
}

app.mount('#app')
