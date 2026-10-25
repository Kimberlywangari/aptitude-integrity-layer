<script setup lang="ts">
import { VUE_QUERY_CLIENT } from '@tanstack/vue-query'
import { onBeforeUnmount, onMounted, provide } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import logo from '../assets/cytonn-logo.png'
import BaseButton from '../components/BaseButton.vue'
import { homeFor, loginPathFor } from '../lib/routes'
import { clearStaff, getStaff } from '../lib/staffSession'
import '../styles/staff.css'
import { clearQueryClient, getQueryClient, setSessionExpiredHandler } from './queryClient'
import RailNav from './RailNav.vue'

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
  <div class="console">
    <aside class="rail">
      <RouterLink :to="homeFor(staff.role)" class="staff-brand">
        <img class="rail-logo" :src="logo" alt="Cytonn: delivering to promise" width="500" height="307" />
        <span>
          <strong>Aptitude Integrity</strong>
          <small>Review console</small>
        </span>
      </RouterLink>
      <!-- RailNav asks for the overview, so it lives in a child: this component provides the query
           client, and a component cannot inject what it provides itself. -->
      <RailNav :role="staff.role" />
      <div class="rail-foot">
        <span class="staff-user">{{ staff.email }} ({{ staff.role }})</span>
        <BaseButton variant="secondary" @click="signOut">Sign out</BaseButton>
      </div>
    </aside>
    <main class="console-main">
      <RouterView />
    </main>
  </div>
</template>
