<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type {
  AdminSitting,
  CloseSittingResponse,
  CreateSittingRequest,
  QuestionBankSummary,
} from '../lib/adminTypes'
import { formatDateTime } from '../lib/format'
import SetupSteps from './SetupSteps.vue'
import { createMessage } from './sittingErrors'

const DEFAULT_PER_SECTION = 4
const DEFAULT_MINUTES = 30
const MIN_MINUTES = 1
const MAX_MINUTES = 240

function toIso(local: string): string | null {
  if (!local) return null
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

const queryClient = useQueryClient()
const name = ref('')
const opensAt = ref('')
const closesAt = ref('')
const minutes = ref(DEFAULT_MINUTES)
const wanted = ref<Record<string, number>>({})
const needsForce = ref<{ id: number; unfinished: number } | null>(null)
const closeError = ref<string | null>(null)

const { data: sittings, isPending: sittingsPending, isError: sittingsError } = useQuery({
  queryKey: ['admin', 'sittings'],
  queryFn: () => api<{ sittings: AdminSitting[] }>('/api/admin/sittings'),
})
const { data: bank } = useQuery({
  queryKey: ['admin', 'bank'],
  queryFn: () => api<QuestionBankSummary>('/api/admin/questions/summary'),
})

// One count per section the bank has, starting at a few so the form is usable straight away. It is
// filled once: later changes to the bank must not overwrite what someone has typed.
const sections = computed(() => bank.value?.by_section ?? [])
watch(
  sections,
  (found) => {
    if (found.length === 0 || Object.keys(wanted.value).length > 0) return
    wanted.value = Object.fromEntries(
      found.map((s) => [s.section, Math.min(DEFAULT_PER_SECTION, s.count)]),
    )
  },
  { immediate: true },
)

const inBank = (section: string) => sections.value.find((s) => s.section === section)?.count ?? 0
const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, Number.isFinite(value) ? Math.round(value) : low))

function setWanted(section: string, value: number) {
  wanted.value = { ...wanted.value, [section]: clamp(value, 0, inBank(section)) }
}

const total = computed(() => Object.values(wanted.value).reduce((n, v) => n + v, 0))
const usedSections = computed(() => Object.values(wanted.value).filter((v) => v > 0).length)

const {
  mutate: createSitting,
  isPending: creating,
  isError: createFailed,
  error: createError,
} = useMutation({
  mutationFn: (body: CreateSittingRequest) =>
    api<AdminSitting>('/api/admin/sittings', { method: 'POST', body }),
  onSuccess: async () => {
    name.value = ''
    await queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })
  },
})

const { mutate: closeSitting, isPending: closing } = useMutation({
  mutationFn: (vars: { id: number; force: boolean }) =>
    api<CloseSittingResponse>(`/api/admin/sittings/${vars.id}/close`, {
      method: 'POST',
      body: { force: vars.force },
    }),
  onSuccess: async () => {
    needsForce.value = null
    closeError.value = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
    ])
  },
  onError: (error, vars) => {
    if (error instanceof ApiError && error.code === 'sessions_unfinished') {
      needsForce.value = { id: vars.id, unfinished: Number(error.body.unfinished ?? 0) }
      closeError.value = null
    } else {
      closeError.value = 'Could not close the sitting.'
    }
  },
})

const createMessageText = computed(() => createMessage(createError.value))
const totalOf = (s: AdminSitting) => s.counts.finished + s.counts.in_progress + s.counts.not_started
const paperOf = (s: AdminSitting) =>
  s.blueprint
    ? Object.entries(s.blueprint)
        .map(([section, n]) => `${section} ${n}`)
        .join(', ')
    : 'spread evenly'

function submit() {
  createSitting({
    name: name.value.trim(),
    opens_at: toIso(opensAt.value),
    closes_at: toIso(closesAt.value),
    duration_s: Math.round(clamp(minutes.value, MIN_MINUTES, MAX_MINUTES) * 60),
    per_section: Object.fromEntries(Object.entries(wanted.value).filter(([, n]) => n > 0)),
  })
}
</script>

<template>
  <SetupSteps v-if="bank && sittings" :bank="bank" :sittings="sittings.sittings" />

  <Banner v-if="bank && bank.synthetic > 0" tone="warn" role="status">
    <p>
      {{ bank.synthetic }} placeholder questions are still in the question bank and can appear on
      real papers. <RouterLink to="/admin/questions">Remove them</RouterLink> before a real sitting.
    </p>
  </Banner>

  <section id="new-sitting" class="panel">
    <h2>New sitting</h2>
    <p class="muted">
      Each candidate gets a different random paper with the numbers below, one timer, and no going
      back.
    </p>
    <form @submit.prevent="submit">
      <label class="field" for="name">Name</label>
      <input id="name" v-model="name" />
      <div class="field-row">
        <div>
          <label class="field" for="opens">Opens (optional)</label>
          <input id="opens" v-model="opensAt" type="datetime-local" />
        </div>
        <div>
          <label class="field" for="closes">Closes (optional)</label>
          <input id="closes" v-model="closesAt" type="datetime-local" />
        </div>
      </div>

      <fieldset>
        <legend>Questions from each section</legend>
        <p v-if="sections.length === 0" class="muted">The question bank is empty.</p>
        <ul v-else class="section-rows">
          <li v-for="s in sections" :key="s.section">
            <span class="name">
              <span class="cap">{{ s.section }}</span>
              <span class="muted"> ({{ s.count }} in the bank)</span>
            </span>
            <span class="stepper">
              <button
                type="button"
                :aria-label="`Fewer ${s.section} questions`"
                :disabled="(wanted[s.section] ?? 0) <= 0"
                @click="setWanted(s.section, (wanted[s.section] ?? 0) - 1)"
              >
                −
              </button>
              <input
                :id="`per-${s.section}`"
                type="number"
                min="0"
                :max="s.count"
                :aria-label="`${s.section} questions`"
                :value="wanted[s.section] ?? 0"
                @change="setWanted(s.section, Number(($event.target as HTMLInputElement).value))"
              />
              <button
                type="button"
                :aria-label="`More ${s.section} questions`"
                :disabled="(wanted[s.section] ?? 0) >= s.count"
                @click="setWanted(s.section, (wanted[s.section] ?? 0) + 1)"
              >
                +
              </button>
            </span>
          </li>
        </ul>
      </fieldset>

      <div class="row-between">
        <label class="field" for="minutes">Time for the whole test (minutes)</label>
        <span class="stepper">
          <button
            type="button"
            aria-label="Less time"
            :disabled="minutes <= MIN_MINUTES"
            @click="minutes = clamp(minutes - 5, MIN_MINUTES, MAX_MINUTES)"
          >
            −
          </button>
          <input id="minutes" v-model.number="minutes" type="number" :min="MIN_MINUTES" :max="MAX_MINUTES" />
          <button
            type="button"
            aria-label="More time"
            :disabled="minutes >= MAX_MINUTES"
            @click="minutes = clamp(minutes + 5, MIN_MINUTES, MAX_MINUTES)"
          >
            +
          </button>
        </span>
      </div>

      <p id="paper-summary" class="muted" role="status">
        {{ total }} question{{ total === 1 ? '' : 's' }} from {{ usedSections }}
        section{{ usedSections === 1 ? '' : 's' }}, {{ minutes }} minutes.
      </p>
      <BaseButton type="submit" :busy="creating" :disabled="!name.trim() || total < 1">
        {{ creating ? 'Creating...' : 'Create sitting' }}
      </BaseButton>
    </form>
    <Banner v-if="createFailed" tone="bad" role="alert"><p>{{ createMessageText }}</p></Banner>
  </section>

  <p v-if="sittingsPending" role="status">Loading sittings...</p>
  <Banner v-if="sittingsError" tone="bad" role="alert"><p>Could not load the sittings.</p></Banner>
  <div v-if="sittings" class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Window</th>
          <th>Limit</th>
          <th>Paper</th>
          <th>Progress</th>
          <th>Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in sittings.sittings" :key="s.id">
          <td>{{ s.name }}</td>
          <td>
            {{
              s.opens_at || s.closes_at
                ? `${formatDateTime(s.opens_at)} to ${formatDateTime(s.closes_at)}`
                : 'Always open'
            }}
          </td>
          <td class="nowrap">{{ Math.round(s.duration_s / 60) }} min</td>
          <td class="paper">
            {{ s.question_count }} questions<br /><span class="muted">{{ paperOf(s) }}</span>
          </td>
          <td>
            {{ s.counts.finished }} of {{ totalOf(s) }} finished<template v-if="s.counts.in_progress > 0">, {{ s.counts.in_progress }} sitting now</template>
          </td>
          <td>
            <span class="pill" :class="s.status === 'open' ? 'ok' : 'plain'">{{ s.status === 'open' ? 'Open' : 'Closed' }}</span>
          </td>
          <td>
            <template v-if="s.status === 'open'">
              <template v-if="needsForce?.id === s.id">
                <span class="muted">{{ needsForce.unfinished }} not finished. </span>
                <BaseButton :disabled="closing" @click="closeSitting({ id: s.id, force: true })">
                  Close anyway (logged)
                </BaseButton>
              </template>
              <BaseButton v-else variant="secondary" :disabled="closing" @click="closeSitting({ id: s.id, force: false })">
                Close sitting
              </BaseButton>
            </template>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <Banner v-if="closeError" tone="bad" role="alert"><p>{{ closeError }}</p></Banner>
  <p class="muted">
    Flags and packets are built after a sitting is closed. Cohort checks need at least 8 finished
    candidates.
  </p>
</template>
