<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type {
  CloseSittingResponse,
  DeleteSittingResponse,
  Invite,
  InviteState,
  RetryPapersResponse,
  SittingCandidate,
  SittingDetail,
} from '../lib/adminTypes'
import { formatDateTime } from '../lib/format'
import { MAIL, RESEND_TITLE } from './mailText'
import PassMarkPanel from './PassMarkPanel.vue'
import ReissuedLink from './ReissuedLink.vue'
import ResultsPanel from './ResultsPanel.vue'
import { paperOf, stateOf, windowOf } from './sittingText'

// One sitting opened up: who was invited, who has done the test and who has not, and the things
// that can be done to the sitting as a whole.
const props = defineProps<{ id: string }>()

const router = useRouter()
const queryClient = useQueryClient()
const sittingId = computed(() => Number(props.id))

// Someone watching a sitting wants to see people arrive, so an open sitting refreshes itself. A tab
// that is not being looked at does not poll.
const REFRESH_MS = 15_000
const {
  data,
  isPending,
  isError,
  error: loadError,
} = useQuery({
  queryKey: computed(() => ['admin', 'sittings', sittingId.value]),
  queryFn: () => api<SittingDetail>(`/api/admin/sittings/${sittingId.value}`),
  refetchInterval: (query) => (query.state.data?.sitting.status === 'open' ? REFRESH_MS : false),
  retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
})
const notFound = computed(() => loadError.value instanceof ApiError && loadError.value.status === 404)

const sitting = computed(() => data.value?.sitting)
const people = computed(() => data.value?.candidates ?? [])
const state = computed(() => (sitting.value ? stateOf(sitting.value) : null))
const isOpen = computed(() => sitting.value?.status === 'open')
const isAi = computed(() => sitting.value?.question_mode === 'ai')

// ---- who is where
const STATE: Record<InviteState, { label: string; pill: string }> = {
  not_opened: { label: 'Not opened', pill: 'plain' },
  opened: { label: 'Opened', pill: 'moderate' },
  started: { label: 'Sitting now', pill: 'moderate' },
  finished: { label: 'Finished', pill: 'ok' },
}
const STATES = Object.keys(STATE) as InviteState[]
const filter = ref<'all' | InviteState>('all')
const countOf = (wanted: InviteState) => people.value.filter((p) => p.state === wanted).length
const shown = computed(() =>
  filter.value === 'all' ? people.value : people.value.filter((p) => p.state === filter.value),
)

// A paper waited for longer than this is offered a restart; the server holds the same number.
const SLOW_WAIT_S = 600
const waitedText = (seconds: number) =>
  seconds < 60 ? 'under a minute' : `${Math.floor(seconds / 60)} min`
const isSlow = (p: SittingCandidate) => (p.waited_s ?? 0) >= SLOW_WAIT_S
const answeredText = (p: SittingCandidate) =>
  p.state === 'started' || p.state === 'finished'
    ? `${p.answered} of ${sitting.value?.question_count ?? 0}`
    : '-'
const stuckPapers = computed(() => people.value.filter((p) => p.paper_status === 'failed' || isSlow(p)).length)

const invalidateAll = () =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ['admin'] }),
    queryClient.invalidateQueries({ queryKey: ['overview'] }),
    // closing and deleting both change what the reviewer lists
    queryClient.invalidateQueries({ queryKey: ['queue'] }),
    queryClient.invalidateQueries({ queryKey: ['candidates'] }),
  ])

// ---- closing
const needsForce = ref<number | null>(null)
const closeError = ref<string | null>(null)
const { mutate: closeSitting, isPending: closing } = useMutation({
  mutationFn: (force: boolean) =>
    api<CloseSittingResponse>(`/api/admin/sittings/${sittingId.value}/close`, {
      method: 'POST',
      body: { force },
    }),
  onSuccess: async () => {
    needsForce.value = null
    closeError.value = null
    await invalidateAll()
  },
  onError: (error) => {
    if (error instanceof ApiError && error.code === 'sessions_unfinished') {
      needsForce.value = Number(error.body.unfinished ?? 0)
      closeError.value = null
    } else closeError.value = 'Could not close the sitting.'
  },
})

// ---- a new link for one person
const reissued = ref<Invite | null>(null)
const { mutate: reissue, isPending: reissuing, isError: reissueFailed } = useMutation({
  mutationFn: (candidateId: string) =>
    api<Invite>(`/api/admin/invites/${encodeURIComponent(candidateId)}/reissue`, { method: 'POST' }),
  onSuccess: (invite) => {
    reissued.value = invite
  },
})

// ---- asking for questions again
const { mutate: restartPapers, isPending: restarting } = useMutation({
  mutationFn: () =>
    api<RetryPapersResponse>(`/api/admin/sittings/${sittingId.value}/retry-papers`, { method: 'POST' }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] }),
})

// ---- deleting
const confirming = ref(false)
const typed = ref('')
const nameMatches = computed(() => !!sitting.value && typed.value.trim() === sitting.value.name)
const deleteStats = computed(() => ({
  codes: people.value.length,
  opened: people.value.filter((p) => p.state !== 'not_opened').length,
  finished: countOf('finished'),
}))

const {
  mutate: deleteSitting,
  isPending: deleting,
  isError: deleteFailed,
  error: deleteError,
  reset: clearDeleteError,
} = useMutation({
  mutationFn: () =>
    api<DeleteSittingResponse>(`/api/admin/sittings/${sittingId.value}/delete`, {
      method: 'POST',
      body: { confirm_name: typed.value.trim() },
    }),
  onSuccess: async () => {
    // leave the page first: refetching a sitting that no longer exists would only show an error
    queryClient.removeQueries({ queryKey: ['admin', 'sittings', sittingId.value] })
    await router.replace('/admin')
    await invalidateAll()
  },
})
const deleteMessage = computed(() => {
  const e = deleteError.value
  if (!deleteFailed.value) return null
  if (e instanceof ApiError) {
    if (e.code === 'sessions_in_progress') {
      const n = Number(e.body.in_progress ?? 0)
      return (
        `${n} ${n === 1 ? 'candidate is' : 'candidates are'} in the middle of the test. Wait until ` +
        'they finish or their time runs out, then try again.'
      )
    }
    if (e.code === 'name_does_not_match') return 'That is not the name of the sitting.'
    if (e.code === 'sitting_not_found') return 'That sitting no longer exists.'
  }
  return 'Could not delete the sitting.'
})

function startDelete() {
  typed.value = ''
  clearDeleteError()
  confirming.value = true
}
</script>

<template>
  <p class="back"><RouterLink to="/admin">All sittings</RouterLink></p>

  <p v-if="isPending" role="status">Loading the sitting...</p>
  <Banner v-else-if="notFound" tone="bad" role="alert">
    <p>That sitting does not exist. It may have been deleted. <RouterLink to="/admin">Back to the sittings</RouterLink></p>
  </Banner>
  <Banner v-else-if="isError" tone="bad" role="alert"><p>Could not load the sitting.</p></Banner>

  <template v-else-if="sitting && state">
    <section class="panel" aria-labelledby="sitting-name">
      <div class="row-between">
        <h2 id="sitting-name">{{ sitting.name }}</h2>
        <span class="pill" :class="state.pill" :title="state.title">{{ state.label }}</span>
      </div>
      <p class="muted facts">
        {{ windowOf(sitting) }} · {{ Math.round(sitting.duration_s / 60) }} minutes ·
        {{ sitting.question_count }} questions ({{ paperOf(sitting) }})
      </p>
      <div class="actions">
        <RouterLink v-if="isOpen" class="btn secondary" :to="{ path: '/admin/invites', query: { sitting: sitting.id } }">
          Make invitations
        </RouterLink>
        <template v-if="isOpen">
          <template v-if="needsForce !== null">
            <span class="muted">{{ needsForce }} not finished.</span>
            <BaseButton :disabled="closing" @click="closeSitting(true)">Close anyway (logged)</BaseButton>
          </template>
          <BaseButton v-else variant="secondary" :disabled="closing" @click="closeSitting(false)">
            Close sitting
          </BaseButton>
        </template>
        <BaseButton v-if="isAi && stuckPapers > 0" variant="secondary" :busy="restarting" @click="restartPapers()">
          Write {{ stuckPapers === 1 ? 'it' : 'them' }} again ({{ stuckPapers }})
        </BaseButton>
        <BaseButton variant="danger" :disabled="confirming" @click="startDelete">Delete sitting</BaseButton>
      </div>
      <Banner v-if="closeError" tone="bad" role="alert"><p>{{ closeError }}</p></Banner>
    </section>

    <section v-if="confirming" class="panel danger-zone" aria-labelledby="delete-title">
      <h2 id="delete-title">Delete "{{ sitting.name }}"?</h2>
      <p>This cannot be undone. It removes:</p>
      <ul>
        <li>
          {{ deleteStats.codes }} {{ deleteStats.codes === 1 ? 'invitation' : 'invitations' }}: their codes stop
          working at once
        </li>
        <li>
          {{ deleteStats.opened }} {{ deleteStats.opened === 1 ? 'person' : 'people' }} who opened their link
          ({{ deleteStats.finished }} finished), with their answers, action logs, flags, reviewer decisions and
          recordings
        </li>
        <li v-if="isAi">the questions written for them</li>
      </ul>
      <p class="muted">
        The audit log keeps a line saying that you deleted it. The question bank is not touched.
      </p>
      <form @submit.prevent="nameMatches && deleteSitting()">
        <label class="field" for="confirm-name">Type the name of the sitting to confirm</label>
        <input id="confirm-name" v-model="typed" autocomplete="off" />
        <div class="actions">
          <BaseButton type="submit" variant="danger" :busy="deleting" :disabled="!nameMatches">
            {{ deleting ? 'Deleting...' : 'Delete for good' }}
          </BaseButton>
          <BaseButton variant="secondary" :disabled="deleting" @click="confirming = false">Cancel</BaseButton>
        </div>
      </form>
      <Banner v-if="deleteMessage" tone="bad" role="alert"><p>{{ deleteMessage }}</p></Banner>
    </section>

    <div class="tiles">
      <div class="tile">
        <h2>Invited</h2>
        <p class="tile-n">{{ people.length }}</p>
      </div>
      <div v-for="s in STATES" :key="s" class="tile">
        <h2>{{ STATE[s].label }}</h2>
        <p class="tile-n">{{ countOf(s) }}</p>
      </div>
    </div>

    <ReissuedLink v-if="reissued" :key="reissued.code" :invite="reissued" @hide="reissued = null" />
    <Banner v-if="reissueFailed" tone="bad" role="alert"><p>Could not make a new code.</p></Banner>

    <p v-if="people.length === 0" class="muted">
      Nobody is invited to this sitting yet.
      <RouterLink v-if="isOpen" :to="{ path: '/admin/invites', query: { sitting: sitting.id } }">Make invitations</RouterLink>
    </p>
    <div v-else class="table-wrap">
      <div class="filters" role="group" aria-label="Show">
        <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">
          All {{ people.length }}
        </button>
        <button v-for="s in STATES" :key="s" type="button" :aria-pressed="filter === s" @click="filter = s">
          {{ STATE[s].label }} {{ countOf(s) }}
        </button>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>Candidate</th>
            <th>Status</th>
            <th>Answered</th>
            <th v-if="isAi">Questions</th>
            <th>Opened</th>
            <th>Finished</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in shown" :key="p.candidate_id">
            <td>
              <span class="mono">{{ p.candidate_id }}</span>
              <template v-if="p.email">
                <br />{{ p.name }} <span class="muted">{{ p.email }}</span>
              </template>
            </td>
            <td>
              <span class="pill" :class="STATE[p.state].pill">{{ STATE[p.state].label }}</span>
              <span v-if="p.invite_mail" class="pill" :class="MAIL[p.invite_mail].pill">
                {{ MAIL[p.invite_mail].label }}
              </span>
              <span v-if="p.result_mail && p.result_mail_status" class="pill" :class="MAIL[p.result_mail_status].pill">
                {{ p.result_mail === 'passed' ? 'Pass' : 'Not-passed' }} email:
                {{ MAIL[p.result_mail_status].label.toLowerCase() }}
              </span>
            </td>
            <td class="nowrap">{{ answeredText(p) }}</td>
            <td v-if="isAi">
              <template v-if="p.paper_status === 'failed'">
                <span class="bad-text">Could not be written</span>
                <br /><span v-if="p.paper_error" class="muted">{{ p.paper_error }}</span>
              </template>
              <template v-else-if="p.paper_status === 'pending'">
                <span :class="isSlow(p) ? 'bad-text' : 'muted'">
                  Being written, waited {{ waitedText(p.waited_s ?? 0) }}
                </span>
              </template>
              <template v-else-if="p.paper_status === 'ready'">Ready</template>
              <template v-else>-</template>
            </td>
            <td class="nowrap">{{ formatDateTime(p.opened_at) }}</td>
            <td class="nowrap">{{ formatDateTime(p.finished_at) }}</td>
            <td>
              <BaseButton
                v-if="isOpen || p.state === 'finished'"
                variant="secondary"
                :disabled="reissuing"
                :aria-label="`Resend link to ${p.candidate_id}`"
                :title="RESEND_TITLE"
                @click="reissue(p.candidate_id)"
              >
                Resend link
              </BaseButton>
            </td>
          </tr>
          <tr v-if="shown.length === 0">
            <td :colspan="isAi ? 7 : 6" class="muted">Nobody here.</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="isOpen" class="muted">This list refreshes by itself while the sitting is open.</p>

    <PassMarkPanel
      :sitting-id="sitting.id"
      :pass-mark="sitting.pass_mark ?? null"
      :question-count="sitting.question_count"
    />
    <ResultsPanel :sitting-id="sitting.id" />
  </template>
</template>

<style scoped>
.back {
  margin: 0 0 0.75rem;
}

a.btn {
  text-decoration: none;
}

.facts {
  margin-top: 0.25rem;
}

.danger-zone {
  border-color: var(--danger);
}

.danger-zone ul {
  padding-left: 1.25rem;
  margin: 0 0 0.75rem;
}
</style>
