<script setup lang="ts">
import { VUE_QUERY_CLIENT } from '@tanstack/vue-query'
import { onBeforeUnmount, onMounted, provide } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import BaseButton from '../components/BaseButton.vue'
import { homeFor, loginPathFor } from '../lib/routes'
import { clearStaff, getStaff } from '../lib/staffSession'
import '../styles/staff.css'
import Breadcrumbs from './Breadcrumbs.vue'
import { clearQueryClient, getQueryClient, setSessionExpiredHandler } from './queryClient'

// Everything staff-facing (the reviewer app and the recruiter's setup screens) is a lazy chunk, and
// so is TanStack Query: it is provided here, not installed for the whole app.
const client = getQueryClient()
provide(VUE_QUERY_CLIENT, client)

const router = useRouter()
const route = useRoute()

// A session that expired mid-use goes back to the sign-in for the part of the app it was in.
onMounted(() => {
  client.mount()
  setSessionExpiredHandler(() => {
    clearStaff()
    clearQueryClient()
    void router.replace(loginPathFor(route.path))
  })
})
onBeforeUnmount(() => {
  setSessionExpiredHandler(null)
  client.unmount()
})
// The router guard only lets a signed-in person reach this layout.
const staff = getStaff()!

function signOut() {
  clearStaff()
  clearQueryClient()
  void router.replace('/') // the entry page, where the three sign-ins are
}
</script>

<template>
  <header class="staff-header">
    <RouterLink :to="homeFor(staff.role)" class="staff-brand">
      <svg class="logo" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" />
        <path d="M9 16.5l4.6 4.6L23 11.5" />
      </svg>
      Integrity review
    </RouterLink>
    <nav aria-label="Main">
      <RouterLink to="/review" exact-active-class="active">Queue</RouterLink>
      <RouterLink to="/review/audit" exact-active-class="active">Audit</RouterLink>
      <template v-if="staff.role === 'admin'">
        <RouterLink to="/admin" exact-active-class="active">Sittings</RouterLink>
        <RouterLink to="/admin/invites" exact-active-class="active">Invites</RouterLink>
        <RouterLink to="/admin/questions" exact-active-class="active">Questions</RouterLink>
      </template>
    </nav>
    <span class="staff-user">{{ staff.email }} ({{ staff.role }})</span>
    <BaseButton variant="secondary" @click="signOut">Sign out</BaseButton>
  </header>
  <main class="page wide">
    <Breadcrumbs />
    <RouterView />
  </main>
</template>

<style scoped>
.logo {
  width: 1.5rem;
  height: 1.5rem;
}

.logo rect {
  fill: var(--accent);
}

.logo path {
  fill: none;
  stroke: var(--on-accent);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
