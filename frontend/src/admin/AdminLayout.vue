<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'

// In the order the work goes: a bank to draw from, a sitting that draws from it, then the people.
const TABS = [
  { to: '/admin', label: 'Sitting setup' },
  { to: '/admin/questions', label: 'Question bank' },
  { to: '/admin/invites', label: 'Invitations' },
]

// A sitting's own page is part of sitting setup, so that tab stays lit while it is open.
const route = useRoute()
const isCurrent = (to: string, exact: boolean) =>
  exact || (to === '/admin' && route.path.startsWith('/admin/sittings/'))
</script>

<template>
  <header class="page-head">
    <div>
      <h1>Admin</h1>
      <p>
        Look after the question bank, set up a sitting and invite candidates. Every change is
        written to the audit log.
      </p>
    </div>
  </header>

  <nav class="tabs" aria-label="Admin sections">
    <RouterLink v-for="tab in TABS" :key="tab.to" :to="tab.to" custom v-slot="{ href, navigate, isExactActive }">
      <a :href="href" :aria-current="isCurrent(tab.to, isExactActive) ? 'page' : undefined" @click="navigate">{{ tab.label }}</a>
    </RouterLink>
  </nav>

  <RouterView />
</template>
