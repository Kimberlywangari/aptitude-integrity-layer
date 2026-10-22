<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import type { IconName } from '../components/icons'
import { api } from '../lib/api'
import type { OverviewResponse } from '../lib/reviewTypes'
import type { StaffRole } from '../lib/staffSession'

const props = defineProps<{ role: StaffRole }>()
const route = useRoute()

// The same query the overview page uses (and the same cache), so the count in the rail costs
// nothing extra on that page. A failure just leaves the count off.
const { data } = useQuery({
  queryKey: ['overview', null],
  queryFn: () => api<OverviewResponse>('/api/review/overview'),
  staleTime: 30_000,
})
const pending = computed(() => data.value?.pending ?? 0)

interface Item {
  to: string
  label: string
  icon: IconName
  on: (path: string) => boolean
  count?: boolean
}

// A link is current for the whole part it opens: the queue stays lit on a candidate's page, the
// admin link on every admin tab. The audit log sits under /review but is its own page.
const items = computed<Item[]>(() => [
  { to: '/overview', label: 'Overview', icon: 'grid', on: (p) => p === '/overview' },
  {
    to: '/review',
    label: 'Review queue',
    icon: 'queue',
    on: (p) => p === '/review' || p.startsWith('/review/candidates/'),
    count: true,
  },
  { to: '/review/audit', label: 'Audit log', icon: 'clipboard', on: (p) => p === '/review/audit' },
  ...(props.role === 'admin'
    ? [
        {
          to: '/admin',
          label: 'Admin',
          icon: 'user' as IconName,
          on: (p: string) => p === '/admin' || p.startsWith('/admin/'),
        },
      ]
    : []),
])
</script>

<template>
  <nav class="rail-nav" aria-label="Main">
    <RouterLink v-for="item in items" :key="item.to" :to="item.to" custom v-slot="{ href, navigate }">
      <a :href="href" :aria-current="item.on(route.path) ? 'page' : undefined" @click="navigate">
        <Icon :name="item.icon" size="1.15rem" />
        <span>{{ item.label }}</span>
        <span v-if="item.count && pending > 0" class="rail-count" :aria-label="`${pending} waiting`">{{
          pending
        }}</span>
      </a>
    </RouterLink>
  </nav>
</template>
