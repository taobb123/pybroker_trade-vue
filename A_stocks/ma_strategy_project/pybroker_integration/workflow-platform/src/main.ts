import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import { useQuotaStore } from './stores/quota'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

const auth = useAuthStore(pinia)
const quota = useQuotaStore(pinia)
void auth
  .bootstrap()
  .then(() => (auth.isAuthenticated ? quota.refresh() : undefined))
  .finally(() => {
    app.mount('#app')
  })
