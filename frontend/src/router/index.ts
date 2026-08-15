import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from '@/views/LibraryView.vue'
import MetadataView from '@/views/MetadataView.vue'
import SettingsView from '@/views/SettingsView.vue'
import LoginView from '@/views/LoginView.vue'
import SetupView from '@/views/SetupView.vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/setup',
      name: 'setup',
      component: SetupView,
      meta: { public: true },
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { public: true },
    },
    {
      path: '/',
      name: 'library',
      component: LibraryView,
    },
    {
      path: '/metadata',
      name: 'metadata',
      component: MetadataView,
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) {
    await auth.load()
  }

  if (auth.setupRequired) {
    if (to.name !== 'setup') return { name: 'setup' }
    return true
  }

  if (to.name === 'setup') {
    return { name: auth.isLoggedIn ? 'library' : 'login' }
  }

  if (!auth.isLoggedIn) {
    if (to.name !== 'login') return { name: 'login' }
    return true
  }

  if (to.name === 'login') {
    return { name: 'library' }
  }

  return true
})

export default router
