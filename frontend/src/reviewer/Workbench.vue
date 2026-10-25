<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import { humaniseKind } from '../lib/format'
import type {
  CandidateRow,
  CandidatesResponse,
  QueueItem,
  QueueResponse,
} from '../lib/reviewTypes'
import BandChip from './BandChip.vue'
import {
  BAND_NOTE,
  EVERYONE_NOTE,
  FLAG_LABELS,
  QUEUE_EMPTY,
  STATUS_LABELS,
  orderBasis,
} from './copy'

type Filter = 'all' | 'pending' | 'high' | 'moderate' | 'low'
type View = 'flagged' | 'everyone'

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
// The queue is the work list. "Everyone" is only fetched once someone asks for it.
const view = ref<View>('flagged')
const sittingQuery = computed(() =>
  sitting.value ? `?sitting=${encodeURIComponent(sitting.value)}` : '',
)

const { data, isPending, isError, refetch } = useQuery({
  queryKey: ['queue', sitting],
  queryFn: () => api<QueueResponse>(`/api/review/queue${sittingQuery.value}`),
})

const {
  data: everyone,
  isPending: everyonePending,
  isError: everyoneError,
  refetch: refetchEveryone,
} = useQuery({
  queryKey: ['candidates', sitting],
  queryFn: () => api<CandidatesResponse>(`/api/review/candidates${sittingQuery.value}`),
  enabled: computed(() => view.value === 'everyone'),
})

function keeps(item: QueueItem): boolean {
  if (filter.value === 'all') return true
  if (filter.value === 'pending') return item.decision === null
  return item.band === filter.value
}

const shown = computed(() => data.value?.items.filter(keeps) ?? [])
// The queue already ends with the candidates whose only flag is a gap in the record.
const laneStart = computed(() => shown.value.findIndex((i) => i.logging_only))

function rowSummary(row: CandidateRow): string {
  if (row.status === 'created') return STATUS_LABELS.created
  if (row.status === 'in_progress') return `${STATUS_LABELS.in_progress} · ${row.resolved} of ${row.total}`
  if (row.flag_count === 0) return `${STATUS_LABELS.finished} · no flags`
  const names = row.flag_kinds.map((kind) => FLAG_LABELS[kind] ?? humaniseKind(kind)).join(', ')
  return `${STATUS_LABELS.finished} · ${row.flag_count} flag${row.flag_count === 1 ? '' : 's'}: ${names}`
}

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
    <section class="panel queue" aria-label="Candidates in this sitting">
      <div class="filters" role="group" aria-label="Which candidates to list">
        <button type="button" :aria-pressed="view === 'flagged'" @click="view = 'flagged'">
          Flagged ({{ data.items.length }})
        </button>
        <button type="button" :aria-pressed="view === 'everyone'" @click="view = 'everyone'">
          Everyone<template v-if="everyone"> ({{ everyone.items.length }})</template>
        </button>
      </div>

      <template v-if="view === 'flagged'">
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

        <p v-if="data.items.length === 0" class="empty-bench">{{ QUEUE_EMPTY }}</p>
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
      </template>

      <template v-else>
        <p v-if="everyonePending" role="status" class="empty-bench">Loading everyone...</p>
        <div v-else-if="everyoneError" class="empty-bench" role="alert">
          Could not load the list.
          <BaseButton variant="secondary" @click="refetchEveryone()">Try again</BaseButton>
        </div>
        <p v-else-if="everyone && everyone.items.length === 0" class="empty-bench">
          Nobody has opened the test in this sitting yet.
        </p>
        <ul v-else-if="everyone" class="q-list">
          <li v-for="row in everyone.items" :key="row.candidate_id">
            <RouterLink :to="to(row.candidate_id)" class="q-item">
              <span class="q-main">
                <strong>{{ row.candidate_id }}</strong>
                <small>{{ rowSummary(row) }}<template v-if="row.shortlisted"> · Shortlisted</template></small>
              </span>
              <span v-if="row.decision" class="pill plain">Decided</span>
              <span v-else-if="row.in_queue" class="pill plain">In queue</span>
            </RouterLink>
          </li>
        </ul>
        <p v-if="everyone" class="muted note">{{ EVERYONE_NOTE }}</p>
      </template>
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
