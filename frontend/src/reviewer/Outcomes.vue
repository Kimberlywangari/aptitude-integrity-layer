<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import { getStaff } from '../lib/staffSession'
import type {
  BulkPassResponse,
  EmailState,
  OutcomeStatus,
  OutcomesResponse,
} from '../lib/reviewTypes'
import { EMAIL_PILLS, STATUS_ORDER, STATUS_PILLS } from './copy'

// Where everyone stands: passed, failed, waiting for review and the rest. A reviewer's copy of the
// list has candidate IDs only; the admin's has names and a masked address, and can be downloaded.
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const isAdmin = getStaff()?.role === 'admin'
const base = isAdmin ? '/api/admin/outcomes' : '/api/review/outcomes'

const sitting = computed(() => (typeof route.query.sitting === 'string' ? route.query.sitting : null))
const status = ref<OutcomeStatus | ''>('')
const email = ref<EmailState | ''>('')
const search = ref('')
const typed = ref('')
const page = ref(1)

// the search box asks the server once the typing stops, not on every key
let wait: ReturnType<typeof setTimeout> | undefined
watch(typed, (value) => {
  clearTimeout(wait)
  wait = setTimeout(() => {
    search.value = value.trim()
    page.value = 1
  }, 250)
})
watch([status, email, sitting], () => {
  page.value = 1
  chosen.value = new Set()
})

const query = computed(() => {
  const p = new URLSearchParams()
  if (sitting.value) p.set('sitting', sitting.value)
  if (status.value) p.set('status', status.value)
  if (email.value) p.set('email', email.value)
  if (search.value) p.set('q', search.value)
  if (page.value > 1) p.set('page', String(page.value))
  const text = p.toString()
  return text ? `?${text}` : ''
})

const { data, isPending, isError, refetch } = useQuery({
  queryKey: ['outcomes', isAdmin, query],
  queryFn: () => api<OutcomesResponse>(`${base}${query.value}`),
  placeholderData: (previous) => previous,
})

const changeSitting = (event: Event) =>
  router.push({ query: { sitting: (event.target as HTMLSelectElement).value } })

// ---- passing several at once
const chosen = ref<Set<string>>(new Set())
const confirming = ref(false)
const outcome = ref<BulkPassResponse | null>(null)
const eligible = computed(() => (data.value?.items ?? []).filter((i) => i.can_mark_passed))
const allChosen = computed(
  () => eligible.value.length > 0 && eligible.value.every((i) => chosen.value.has(i.candidate_id)),
)
function toggle(id: string) {
  const next = new Set(chosen.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  chosen.value = next
  confirming.value = false
}
function toggleAll() {
  chosen.value = allChosen.value ? new Set() : new Set(eligible.value.map((i) => i.candidate_id))
  confirming.value = false
}

const {
  mutate: markPassed,
  isPending: marking,
  isError: markFailed,
} = useMutation({
  mutationFn: () =>
    api<BulkPassResponse>('/api/review/results/bulk-pass', {
      method: 'POST',
      body: { sitting_id: data.value?.sitting_id, candidate_ids: [...chosen.value] },
    }),
  onSuccess: async (result) => {
    outcome.value = result
    confirming.value = false
    chosen.value = new Set()
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['outcomes'] }),
      queryClient.invalidateQueries({ queryKey: ['candidate'] }),
      queryClient.invalidateQueries({ queryKey: ['audit'] }),
    ])
  },
})

// ---- the admin's download: the token goes in a header, so it is fetched and saved, not linked to
const downloadFailed = ref(false)
async function download() {
  downloadFailed.value = false
  try {
    const id = data.value?.sitting_id
    const response = await fetch(`/api/admin/outcomes.csv?sitting=${id}`, {
      headers: { Authorization: `Bearer ${getStaff()?.token ?? ''}` },
    })
    if (!response.ok) throw new Error(String(response.status))
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = `outcomes-${id}.csv`
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    downloadFailed.value = true
  }
}

const scoreText = (score: number | null, total: number | null) =>
  score === null ? '-' : `${score} of ${total}`
const lastPage = computed(() =>
  data.value ? Math.max(1, Math.ceil(data.value.matching / data.value.page_size)) : 1,
)
const from = computed(() => (data.value && data.value.matching ? (page.value - 1) * data.value.page_size + 1 : 0))
const to = computed(() =>
  data.value ? Math.min(data.value.matching, page.value * data.value.page_size) : 0,
)
const REFUSED: Record<string, string> = {
  review_first: 'flagged, record a decision first',
  already_emailed: 'already emailed',
  no_email: 'no email address',
  not_finished: 'has not finished',
  candidate_not_found: 'not found',
}
</script>

<template>
  <p v-if="isPending" role="status">Loading the outcomes...</p>
  <Banner v-else-if="isError" tone="bad" role="alert">
    <p>
      Could not load the outcomes.
      <BaseButton variant="secondary" @click="refetch()">Try again</BaseButton>
    </p>
  </Banner>

  <template v-else-if="data">
    <header class="page-head">
      <div>
        <h1>Outcomes</h1>
        <p>
          Who has passed, who has not, and who is waiting.
          <template v-if="data.pass_mark !== null">
            Pass mark: {{ data.pass_mark }} of {{ data.question_count }} correct.
          </template>
          <template v-else>No pass mark is set for this sitting.</template>
        </p>
      </div>
      <div v-if="data.sittings.length > 0">
        <label class="sr-only" for="sitting">Sitting</label>
        <select id="sitting" :value="data.sitting_id" @change="changeSitting">
          <option v-for="s in data.sittings" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>
    </header>

    <p v-if="data.sittings.length === 0">
      There is no sitting yet. An admin creates one under Admin, then invites the candidates.
    </p>

    <template v-else>
      <section class="panel" aria-labelledby="outcomes-heading">
        <div class="row-between">
          <h2 id="outcomes-heading">{{ data.total }} invited</h2>
          <BaseButton v-if="isAdmin" variant="secondary" @click="download">Download as CSV</BaseButton>
        </div>
        <Banner v-if="downloadFailed" tone="bad" role="alert"><p>Could not download the list.</p></Banner>

        <div class="filters" role="group" aria-label="Show">
          <button type="button" :aria-pressed="status === ''" @click="status = ''">
            All {{ data.total }}
          </button>
          <button
            v-for="key in STATUS_ORDER"
            :key="key"
            type="button"
            :aria-pressed="status === key"
            @click="status = key"
          >
            {{ STATUS_PILLS[key].label }} {{ data.counts[key] }}
          </button>
        </div>

        <div class="filters">
          <label class="sr-only" for="email-state">Email</label>
          <select id="email-state" v-model="email">
            <option value="">Any email state</option>
            <option v-for="(pill, key) in EMAIL_PILLS" :key="key" :value="key">
              Email: {{ pill.label.toLowerCase() }} ({{ data.email_counts[key] }})
            </option>
          </select>
          <label class="sr-only" for="find">Find a candidate</label>
          <input id="find" v-model="typed" type="search" placeholder="Find by candidate ID" autocomplete="off" />
        </div>

        <div v-if="eligible.length > 0" class="actions">
          <template v-if="confirming">
            <span role="alert">
              Pass {{ chosen.size }} {{ chosen.size === 1 ? 'candidate' : 'candidates' }} and send each their
              pass email now? An email cannot be taken back.
            </span>
            <BaseButton :busy="marking" @click="markPassed()">Yes, pass and send</BaseButton>
            <BaseButton variant="secondary" @click="confirming = false">Cancel</BaseButton>
          </template>
          <BaseButton v-else variant="secondary" :disabled="chosen.size === 0" @click="confirming = true">
            Mark {{ chosen.size }} selected as passed and send emails
          </BaseButton>
        </div>
        <Banner v-if="markFailed" tone="bad" role="alert"><p>Could not send those results.</p></Banner>
        <Banner v-if="outcome" tone="good" role="status">
          <p>
            {{ outcome.queued }} pass {{ outcome.queued === 1 ? 'email is' : 'emails are' }} on the way.
            <template v-if="outcome.refused.length > 0">
              Not done: {{
                outcome.refused.map((r) => `${r.candidate_id} (${REFUSED[r.code] ?? r.code})`).join(', ')
              }}.
            </template>
          </p>
        </Banner>

        <p v-if="data.matching === 0" class="muted">Nobody matches this.</p>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select everyone who can be passed"
                    :checked="allChosen"
                    :disabled="eligible.length === 0"
                    @change="toggleAll"
                  />
                </th>
                <th>Candidate</th>
                <th>Status</th>
                <th>Score</th>
                <th>Flags</th>
                <th>Email</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in data.items" :key="item.candidate_id">
                <td>
                  <input
                    type="checkbox"
                    :aria-label="`Select ${item.candidate_id}`"
                    :checked="chosen.has(item.candidate_id)"
                    :disabled="!item.can_mark_passed"
                    @change="toggle(item.candidate_id)"
                  />
                </td>
                <td>
                  <RouterLink class="mono" :to="`/review/candidates/${item.candidate_id}`">{{
                    item.candidate_id
                  }}</RouterLink>
                  <template v-if="isAdmin && item.name">
                    <br />{{ item.name }} <span class="muted">{{ item.email }}</span>
                  </template>
                  <template v-else-if="!item.has_email && item.status !== 'invited'">
                    <br /><span class="muted">no email address</span>
                  </template>
                </td>
                <td>
                  <span class="pill" :class="STATUS_PILLS[item.status].tone">{{
                    STATUS_PILLS[item.status].label
                  }}</span>
                </td>
                <td>{{ scoreText(item.score, item.total) }}</td>
                <td>{{ item.flag_count }}</td>
                <td>
                  <span class="pill" :class="EMAIL_PILLS[item.email_state].tone">{{
                    EMAIL_PILLS[item.email_state].label
                  }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="data.matching > 0" class="actions">
          <span class="muted">Showing {{ from }} to {{ to }} of {{ data.matching }}.</span>
          <BaseButton variant="secondary" :disabled="page <= 1" @click="page -= 1">Previous</BaseButton>
          <BaseButton variant="secondary" :disabled="page >= lastPage" @click="page += 1">Next</BaseButton>
        </div>
      </section>
    </template>
  </template>
</template>
