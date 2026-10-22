<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import type { QueueItem, QueueResponse } from '../lib/reviewTypes'
import BandChip from './BandChip.vue'
import { BAND_NOTE, orderBasis } from './copy'

type Filter = 'all' | 'pending' | 'high' | 'moderate' | 'low'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'high', label: 'High' },
  { key: 'moderate', label: 'Moderate' },
  { key: 'low', label: 'Low' },
]

const route = useRoute()
const router = useRouter()
const sitting = computed(() => (typeof route.query.sitting === 'string' ? route.query.sitting : null))
const filter = ref<Filter>('all')

const { data, isPending, isError, refetch } = useQuery({
  queryKey: ['queue', sitting],
  queryFn: () =>
    api<QueueResponse>(
      `/api/review/queue${sitting.value ? `?sitting=${encodeURIComponent(sitting.value)}` : ''}`,
    ),
})

function keeps(item: QueueItem): boolean {
  if (filter.value === 'all') return true
  if (filter.value === 'pending') return item.decision === null
  return item.band === filter.value
}

const shown = computed(() => data.value?.items.filter(keeps) ?? [])
// The queue already ends with the candidates whose only flag is a gap in the record.
const laneStart = computed(() => shown.value.findIndex((i) => i.logging_only))

const changeSitting = (event: Event) =>
  router.push({ path: '/review', query: { sitting: (event.target as HTMLSelectElement).value } })
const to = (id: string) => ({
  path: `/review/candidates/${encodeURIComponent(id)}`,
  query: sitting.value ? { sitting: sitting.value } : {},
})
</script>

<template>
  <header class="page-head">
    <div>
      <h1>Review queue</h1>
      <p>
        Ranked by the rules and explained by the AI. The order is a suggestion to help you start;
        nobody is set aside, and the AI never decides anything.
      </p>
    </div>
    <div v-if="data && data.sittings.length > 0">
      <label class="sr-only" for="sitting">Sitting</label>
      <select id="sitting" :value="data.sitting_id" @change="changeSitting">
        <option v-for="s in data.sittings" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </div>
  </header>

  <p v-if="isPending" role="status">Loading the queue...</p>
  <Banner v-else-if="isError" tone="bad" role="alert">
    <p>
      Could not load the queue.
      <BaseButton variant="secondary" @click="refetch()">Try again</BaseButton>
    </p>
  </Banner>

  <div v-else-if="data" class="bench">
    <section class="panel queue" aria-label="Flagged candidates">
      <div class="filters" role="group" aria-label="Filter the queue">
        <button
          v-for="f in FILTERS"
          :key="f.key"
          type="button"
          :aria-pressed="filter === f.key"
          @click="filter = f.key"
        >
          {{ f.label }}
        </button>
      </div>

      <p v-if="data.items.length === 0" class="empty-bench">
        No flagged candidates in this sitting yet. Flags appear once the sitting is closed and the
        jobs have run.
      </p>
      <p v-else-if="shown.length === 0" class="empty-bench">Nobody matches this filter.</p>

      <ul v-else class="q-list">
        <template v-for="(item, index) in shown" :key="item.candidate_id">
          <li v-if="index === laneStart" class="lane-label">
            Logging problems only (low priority)
          </li>
          <li>
            <RouterLink :to="to(item.candidate_id)" class="q-item" :title="orderBasis(item.ai_status, item.ai_strength)">
              <span class="q-rank">{{ item.rank }}</span>
              <span class="q-main">
                <strong>{{ item.candidate_id }}</strong>
                <small>
                  {{ item.flag_count }} flag{{ item.flag_count === 1 ? '' : 's' }}<template v-if="item.shortlisted"> · Shortlisted</template>
                </small>
              </span>
              <span v-if="item.decision" class="pill plain">Decided</span>
              <BandChip v-else :band="item.band" />
            </RouterLink>
          </li>
        </template>
      </ul>
      <p v-if="data.items.length > 0" class="muted note">{{ BAND_NOTE }}</p>
    </section>

    <div class="stack">
      <RouterView />
    </div>
  </div>
</template>

<style scoped>
.note {
  padding: 0.75rem 0.85rem;
  margin: 0;
  font-size: 0.8rem;
  border-top: 1px solid var(--line-soft);
}
</style>
