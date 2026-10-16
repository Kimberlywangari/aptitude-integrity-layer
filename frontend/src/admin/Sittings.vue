<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
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

const CREATE_ERRORS: Record<string, string> = {
  name_required: 'Give the sitting a name.',
  name_too_long: 'That name is too long. Use 100 characters or fewer.',
  name_taken: 'A sitting with that name already exists.',
  invalid_duration: 'The duration must be at least one minute.',
  invalid_question_count: 'The sitting needs at least one question.',
  invalid_window: 'It must close after it opens.',
}

function createMessage(error: unknown): string | null {
  if (!error) return null
  if (error instanceof ApiError) {
    if (error.code === 'question_bank_too_small') {
      return `The question bank has only ${String(error.body.available ?? 'a few')} questions.`
    }
    return CREATE_ERRORS[error.code] ?? 'Could not create the sitting.'
  }
  return 'Could not create the sitting.'
}

function toIso(local: string): string | null {
  if (!local) return null
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

const queryClient = useQueryClient()
const name = ref('')
const opensAt = ref('')
const closesAt = ref('')
const minutes = ref(30)
const count = ref(12)
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
    await queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })
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

function submit() {
  createSitting({
    name: name.value.trim(),
    opens_at: toIso(opensAt.value),
    closes_at: toIso(closesAt.value),
    duration_s: Math.round(minutes.value * 60),
    question_count: Math.round(count.value),
  })
}
</script>

<template>
  <h1>Sittings</h1>

  <SetupSteps v-if="bank && sittings" :bank="bank" :sittings="sittings.sittings" />

  <Banner v-if="bank && bank.synthetic > 0" tone="warn" role="status">
    <p>
      {{ bank.synthetic }} placeholder questions are still in the question bank and can appear on
      real papers. <RouterLink to="/admin/questions">Remove them</RouterLink> before a real sitting.
    </p>
  </Banner>

  <section id="new-sitting" class="panel">
    <h2>New sitting</h2>
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
      <div class="field-row">
        <div>
          <label class="field" for="minutes">Time limit (minutes)</label>
          <input id="minutes" v-model.number="minutes" type="number" min="1" />
        </div>
        <div>
          <label class="field" for="count">Questions per candidate</label>
          <input id="count" v-model.number="count" type="number" min="1" />
        </div>
      </div>
      <BaseButton type="submit" :busy="creating" :disabled="!name.trim()">
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
          <th>Questions</th>
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
          <td>{{ Math.round(s.duration_s / 60) }} min</td>
          <td>{{ s.question_count }}</td>
          <td>
            {{ s.counts.finished }} of {{ totalOf(s) }} finished<template v-if="s.counts.in_progress > 0">, {{ s.counts.in_progress }} sitting now</template>
          </td>
          <td>{{ s.status === 'open' ? 'Open' : 'Closed' }}</td>
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
