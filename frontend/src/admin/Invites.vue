<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type {
  AdminSitting,
  Invite,
  InviteListResponse,
  InvitesResponse,
  InviteState,
  ListProblemReason,
  MailStatus,
  PreviewList,
} from '../lib/adminTypes'
import { invitesToCsv } from '../lib/csv'
import { formatDateTime } from '../lib/format'
import { formatInviteCode } from '../lib/inviteCode'
import { MAIL, RESEND_TITLE } from './mailText'
import ReissuedLink from './ReissuedLink.vue'

const MAX_INVITES = 500

// What each state means for the person running the sitting. The words carry it; colour helps.
const STATE: Record<InviteState, { label: string; pill: string }> = {
  not_opened: { label: 'Not opened', pill: 'plain' },
  opened: { label: 'Opened', pill: 'moderate' },
  started: { label: 'Started', pill: 'moderate' },
  finished: { label: 'Finished', pill: 'ok' },
}

// What is wrong with a line of the pasted list, said after the line's own text.
const REASONS: Record<ListProblemReason, string> = {
  bad_email: 'does not have a valid email address',
  name_missing: 'has no name',
  name_too_long: 'has a name over 200 characters',
  repeated: 'repeats an email from a line above',
  already_invited: 'is already invited to this sitting',
}

// What a sitting's questions are, in the words used on the sitting form.
const MODE_NAME: Record<string, string> = {
  cytonn: "Cytonn's questions",
  ai: 'written by AI',
  practice: 'practice questions',
  bank: 'question bank',
}

const queryClient = useQueryClient()
const route = useRoute()
const count = ref(20)
const sittingId = ref<number | null>(null)
const generatedFor = ref('')
const invites = ref<Invite[] | null>(null)
const reissued = ref<Invite | null>(null)

const { data: listed, isPending: listPending, isError: listFailed } = useQuery({
  queryKey: ['admin', 'invites'],
  queryFn: () => api<InviteListResponse>('/api/admin/invites'),
})

const { data: sittingList } = useQuery({
  queryKey: ['admin', 'sittings'],
  queryFn: () => api<{ sittings: AdminSitting[] }>('/api/admin/sittings'),
})
// Codes can only be made for a sitting that is open; the newest is offered first, unless the page
// was opened from a sitting's own page (?sitting=7), which asks for that one.
const openSittings = computed(() => (sittingList.value?.sittings ?? []).filter((s) => s.status === 'open'))
const asked = computed(() => Number(route.query.sitting))
watch(
  openSittings,
  (list) => {
    if (list.some((s) => s.id === sittingId.value)) return
    sittingId.value = (list.find((s) => s.id === asked.value) ?? list[0])?.id ?? null
  },
  { immediate: true },
)
const chosen = computed(() => openSittings.value.find((s) => s.id === sittingId.value) ?? null)
const describe = (s: AdminSitting) =>
  `${s.name} (${MODE_NAME[s.question_mode] ?? s.question_mode}, ${s.question_count} questions, ` +
  `${Math.round(s.duration_s / 60)} min)`

// Codes for a sitting that opens later are fine, but candidates are turned away until then.
const opensLater = computed(() => {
  const opens = chosen.value?.opens_at
  return opens && Date.now() < Date.parse(opens) ? formatDateTime(opens) : null
})

const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] })

// ---- people: a pasted or uploaded list, one `name, email` per line
const listText = ref('')
const checked = ref<PreviewList | null>(null)
const checkedText = ref('') // what was checked: any change to the text asks for another check
const testTo = ref('')

const { data: mailStatus } = useQuery({
  queryKey: ['admin', 'mail'],
  queryFn: () => api<MailStatus>('/api/admin/mail'),
})
const refreshMail = () => queryClient.invalidateQueries({ queryKey: ['admin', 'mail'] })

watch(listText, (text) => {
  if (text !== checkedText.value) checked.value = null
})

async function onFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) listText.value = await file.text()
}

const {
  mutate: checkList,
  isPending: checking,
  isError: checkFailed,
} = useMutation({
  mutationFn: (vars: { text: string; sitting: number }) =>
    api<PreviewList>('/api/admin/invites/preview', {
      method: 'POST',
      body: { list_text: vars.text, sitting_id: vars.sitting },
    }),
  onSuccess: (data, vars) => {
    checked.value = data
    checkedText.value = vars.text
  },
})

const {
  mutate: createFromList,
  isPending: creatingFromList,
  isError: listCreateFailed,
} = useMutation({
  mutationFn: (vars: { text: string; sitting: number }) =>
    api<InvitesResponse>('/api/admin/invites', {
      method: 'POST',
      body: { list_text: vars.text, sitting_id: vars.sitting },
    }),
  onSuccess: async (data) => {
    invites.value = data.invites
    generatedFor.value = data.sitting_name
    listText.value = ''
    checked.value = null
    await Promise.all([
      refresh(),
      refreshMail(),
      queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] }),
    ])
  },
})

const {
  mutate: sendTest,
  isPending: sendingTest,
  isSuccess: testSent,
  isError: testFailed,
  error: testError,
  reset: clearTest,
} = useMutation({
  mutationFn: (to: string) =>
    api<{ sent: boolean }>('/api/admin/mail/test', { method: 'POST', body: { to } }),
})
const testMessage = computed(() => {
  const e = testError.value
  if (e instanceof ApiError && e.code === 'mail_failed' && typeof e.body.detail === 'string') {
    return `The mail server said: ${e.body.detail}`
  }
  return 'Could not send the test email.'
})

const { mutate: retryFailed, isPending: retrying } = useMutation({
  mutationFn: () => api<{ requeued: number }>('/api/admin/mail/retry', { method: 'POST' }),
  onSuccess: () => Promise.all([refresh(), refreshMail()]),
})

const canCheck = computed(() => listText.value.trim() !== '' && chosen.value !== null)
const canCreate = computed(
  () => checked.value !== null && checked.value.problems.length === 0 && checked.value.people.length > 0,
)

const {
  mutate: generate,
  isPending,
  isError,
  error: generateError,
} = useMutation({
  mutationFn: (vars: { n: number; sitting: number }) =>
    api<InvitesResponse>('/api/admin/invites', {
      method: 'POST',
      body: { count: vars.n, sitting_id: vars.sitting },
    }),
  onSuccess: async (data) => {
    invites.value = data.invites
    generatedFor.value = data.sitting_name
    await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })])
  },
})

const {
  mutate: reissue,
  isPending: reissuing,
  isError: reissueFailed,
} = useMutation({
  mutationFn: (candidateId: string) =>
    api<Invite>(`/api/admin/invites/${encodeURIComponent(candidateId)}/reissue`, { method: 'POST' }),
  onSuccess: (data) => {
    reissued.value = data
  },
})

const valid = computed(
  () =>
    Number.isFinite(count.value) &&
    count.value >= 1 &&
    count.value <= MAX_INVITES &&
    chosen.value !== null,
)
const generateMessage = computed(() => {
  const e = generateError.value
  if (e instanceof ApiError) {
    if (e.code === 'sitting_closed') return 'That sitting has closed. Pick one that is open.'
    if (e.code === 'no_open_sitting') return 'No sitting is open. Create one first.'
    if (e.code === 'sitting_required') return 'Pick which sitting these codes are for.'
  }
  return 'Could not generate the codes.'
})

function download(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function downloadCsv() {
  if (!invites.value) return
  download(
    'invites.csv',
    invitesToCsv(
      invites.value.map((i) => ({ ...i, code: formatInviteCode(i.code) })),
      window.location.origin,
      generatedFor.value,
    ),
  )
}
</script>

<template>
  <p class="muted">
    Each candidate gets one personal code, made for one sitting: it opens that sitting's paper (Cytonn's
    questions, AI-written ones or practice ones, whatever the sitting was made with) for as long as that
    sitting allows. Paste the people to invite, one per line, and each is emailed their own link; they
    type the code and their email on the first screen. Only the people on your list can start. Names and
    emails stay on this screen and in the emails: reviewers and the AI only ever see the candidate ID.
  </p>

  <Banner v-if="mailStatus && !mailStatus.set_up" tone="warn" role="status">
    <p>
      Mail is not set up yet, so invitation emails wait in a queue and are not sent. Set it up in
      <code>.env</code> (see <code>docs/plan/email-setup.md</code>), or download the CSV after creating the
      invitations and send each person their code and link yourself.
    </p>
  </Banner>
  <Banner v-else-if="mailStatus && mailStatus.failed > 0" tone="bad" role="alert">
    <p>
      {{ mailStatus.failed }} {{ mailStatus.failed === 1 ? 'email' : 'emails' }} could not be sent.
      <BaseButton variant="secondary" :busy="retrying" @click="retryFailed()">Try them again</BaseButton>
    </p>
  </Banner>

  <section class="panel" aria-labelledby="people-heading">
    <h2 id="people-heading">Invite people</h2>
    <label class="field" for="sitting">For which sitting</label>
    <select id="sitting" v-model.number="sittingId" :disabled="openSittings.length === 0">
      <option v-for="s in openSittings" :key="s.id" :value="s.id">{{ describe(s) }}</option>
    </select>
    <p v-if="openSittings.length === 0" class="muted" role="status">
      No sitting is open. <RouterLink to="/admin">Create one first</RouterLink>.
    </p>
    <Banner v-if="opensLater" tone="warn" role="status">
      <p>
        This sitting does not open until {{ opensLater }}. Candidates who use their code before then are told
        when to come back.
      </p>
    </Banner>

    <label class="field" for="people">People (one per line: name, email)</label>
    <textarea
      id="people"
      v-model="listText"
      rows="8"
      spellcheck="false"
      placeholder="Ada Lovelace, ada@example.org"
    />
    <p class="muted">
      Or choose a file:
      <input type="file" accept=".csv,.txt,text/csv,text/plain" aria-label="Upload a list" @change="onFile" />
    </p>

    <div class="actions">
      <BaseButton
        variant="secondary"
        :busy="checking"
        :disabled="!canCheck"
        @click="chosen && checkList({ text: listText, sitting: chosen.id })"
      >
        Check the list
      </BaseButton>
      <BaseButton
        :busy="creatingFromList"
        :disabled="!canCreate || !chosen"
        @click="chosen && createFromList({ text: listText, sitting: chosen.id })"
      >
        Create invitations and send emails
      </BaseButton>
    </div>
    <Banner v-if="checkFailed || listCreateFailed" tone="bad" role="alert">
      <p>Could not {{ listCreateFailed ? 'create the invitations' : 'check the list' }}. Check the list and try again.</p>
    </Banner>
    <template v-if="checked">
      <Banner v-if="checked.problems.length === 0" tone="good" role="status">
        <p>
          {{ checked.people.length }} {{ checked.people.length === 1 ? 'person is' : 'people are' }} ready to
          invite to "{{ checked.sitting_name }}".
        </p>
      </Banner>
      <Banner v-else tone="bad" role="alert">
        <p>
          Fix {{ checked.problems.length }} {{ checked.problems.length === 1 ? 'line' : 'lines' }} before
          anyone is invited. Nobody is created while a line has a problem.
        </p>
        <ul id="list-problems">
          <li v-for="p in checked.problems" :key="p.line">
            Line {{ p.line }} ({{ p.text }}) {{ REASONS[p.reason] }}.
          </li>
        </ul>
      </Banner>
    </template>

    <div v-if="mailStatus?.set_up" class="test-mail">
      <h3>Check your mail settings</h3>
      <p class="muted">
        Sends one email now, from {{ mailStatus.from_address }}, to the address you give.
      </p>
      <label class="field" for="test-to">Send a test email to</label>
      <input id="test-to" v-model="testTo" type="email" autocomplete="off" @input="clearTest()" />
      <BaseButton variant="secondary" :busy="sendingTest" :disabled="!testTo.trim()" @click="sendTest(testTo.trim())">
        Send a test email
      </BaseButton>
      <Banner v-if="testSent" tone="good" role="status"><p>Sent. Check that inbox.</p></Banner>
      <Banner v-if="testFailed" tone="bad" role="alert"><p>{{ testMessage }}</p></Banner>
    </div>
  </section>

  <form
    class="panel"
    @submit.prevent="chosen && generate({ n: Math.round(count), sitting: chosen.id })"
  >
    <h2>Codes without an email</h2>
    <p class="muted">For practice and testing: anonymous codes, no emails sent. Use the sitting chosen above.</p>
    <label class="field" for="count">How many new codes (1 to {{ MAX_INVITES }})</label>
    <input id="count" v-model.number="count" type="number" min="1" :max="MAX_INVITES" />
    <BaseButton type="submit" :disabled="!valid" :busy="isPending">
      {{ isPending ? 'Generating...' : 'Generate codes' }}
    </BaseButton>
    <Banner v-if="isError" tone="bad" role="alert"><p>{{ generateMessage }}</p></Banner>
  </form>

  <section v-if="invites" class="panel">
    <h2>{{ invites.length }} new codes</h2>
    <p class="muted">For "{{ generatedFor }}".</p>
    <Banner tone="warn" role="status">
      <p>These are shown once. The server keeps only a hash, so download the list now.</p>
    </Banner>
    <div class="actions">
      <BaseButton @click="downloadCsv">Download CSV</BaseButton>
      <BaseButton variant="secondary" @click="invites = null">Clear this list</BaseButton>
    </div>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Candidate ID</th>
            <th v-if="invites.some((i) => i.email)">Name</th>
            <th v-if="invites.some((i) => i.email)">Email</th>
            <th>Code</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in invites" :key="i.candidate_id">
            <td>{{ i.candidate_id }}</td>
            <td v-if="invites.some((x) => x.email)">{{ i.name }}</td>
            <td v-if="invites.some((x) => x.email)">{{ i.email }}</td>
            <td class="mono">{{ formatInviteCode(i.code) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="panel" aria-labelledby="who">
    <h2 id="who">Candidates</h2>
    <p class="muted">
      Where each one is, read off their newest session. A new code replaces the old one at once,
      so use it for a lost link.
    </p>

    <ReissuedLink v-if="reissued" :key="reissued.code" :invite="reissued" @hide="reissued = null" />
    <Banner v-if="reissueFailed" tone="bad" role="alert"><p>Could not make a new code.</p></Banner>

    <p v-if="listPending" role="status">Loading the candidates...</p>
    <Banner v-else-if="listFailed" tone="bad" role="alert"><p>Could not load the candidates.</p></Banner>
    <template v-else-if="listed">
      <p v-if="listed.invites.length === 0" class="muted">No invitations yet.</p>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Name and email</th>
              <th>Sitting</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in listed.invites" :key="i.candidate_id">
              <td class="mono">{{ i.candidate_id }}</td>
              <td>
                <template v-if="i.email">{{ i.name }} <span class="muted">{{ i.email }}</span></template>
                <span v-else class="muted">no email</span>
              </td>
              <td>{{ i.sitting_name ?? 'The newest open sitting' }}</td>
              <td>
                <span class="pill" :class="STATE[i.status].pill">{{ STATE[i.status].label }}</span>
                <span v-if="i.invite_mail" class="pill" :class="MAIL[i.invite_mail].pill">
                  {{ MAIL[i.invite_mail].label }}
                </span>
              </td>
              <td>
                <BaseButton
                  variant="secondary"
                  :disabled="reissuing"
                  :aria-label="`Resend link to ${i.candidate_id}`"
                  :title="RESEND_TITLE"
                  @click="reissue(i.candidate_id)"
                >
                  Resend link
                </BaseButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="listed.total > listed.invites.length" class="muted">
        Showing the newest {{ listed.invites.length }} of {{ listed.total }}.
      </p>
    </template>
  </section>
</template>
