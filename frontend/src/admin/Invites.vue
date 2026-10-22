<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import type { Invite, InviteListResponse, InvitesResponse, InviteState } from '../lib/adminTypes'
import { invitesToCsv } from '../lib/csv'
import { formatInviteCode } from '../lib/inviteCode'

const MAX_INVITES = 500

// What each state means for the person running the sitting. The words carry it; colour helps.
const STATE: Record<InviteState, { label: string; pill: string }> = {
  not_opened: { label: 'Not opened', pill: 'plain' },
  opened: { label: 'Opened', pill: 'moderate' },
  started: { label: 'Started', pill: 'moderate' },
  finished: { label: 'Finished', pill: 'ok' },
}

const queryClient = useQueryClient()
const count = ref(20)
const invites = ref<Invite[] | null>(null)
const reissued = ref<Invite | null>(null)
const copied = ref(false)

const { data: listed, isPending: listPending, isError: listFailed } = useQuery({
  queryKey: ['admin', 'invites'],
  queryFn: () => api<InviteListResponse>('/api/admin/invites'),
})

const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin', 'invites'] })

const {
  mutate: generate,
  isPending,
  isError,
} = useMutation({
  mutationFn: (n: number) =>
    api<InvitesResponse>('/api/admin/invites', { method: 'POST', body: { count: n } }),
  onSuccess: async (data) => {
    invites.value = data.invites
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
    copied.value = false
  },
})

const valid = computed(
  () => Number.isFinite(count.value) && count.value >= 1 && count.value <= MAX_INVITES,
)
const linkFor = (code: string) => `${window.location.origin}/?t=${formatInviteCode(code)}`

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
    ),
  )
}

async function copyLink(code: string) {
  try {
    await navigator.clipboard.writeText(linkFor(code))
    copied.value = true
  } catch {
    copied.value = false // the link is on screen, so it can still be selected and copied by hand
  }
}
</script>

<template>
  <p class="muted">
    Each candidate gets one personal code. Send them their own link from the CSV, or just the code:
    they type it on the first screen. Candidate IDs are opaque: keep the list of who holds which ID
    on your side, it is never stored here.
  </p>

  <form class="panel" @submit.prevent="generate(Math.round(count))">
    <h2>New invitations</h2>
    <label class="field" for="count">How many new codes (1 to {{ MAX_INVITES }})</label>
    <input id="count" v-model.number="count" type="number" min="1" :max="MAX_INVITES" />
    <BaseButton type="submit" :disabled="!valid" :busy="isPending">
      {{ isPending ? 'Generating...' : 'Generate codes' }}
    </BaseButton>
    <Banner v-if="isError" tone="bad" role="alert"><p>Could not generate the codes.</p></Banner>
  </form>

  <section v-if="invites" class="panel">
    <h2>{{ invites.length }} new codes</h2>
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
            <th>Code</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in invites" :key="i.candidate_id">
            <td>{{ i.candidate_id }}</td>
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

    <div v-if="reissued" class="tokenbox" role="status">
      <span>
        New link for <b>{{ reissued.candidate_id }}</b
        >, shown once. The old code no longer works.
      </span>
      <code>{{ linkFor(reissued.code) }}</code>
      <BaseButton variant="secondary" @click="copyLink(reissued.code)">
        {{ copied ? 'Copied' : 'Copy link' }}
      </BaseButton>
      <BaseButton variant="ghost" @click="reissued = null">Hide</BaseButton>
    </div>
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
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in listed.invites" :key="i.candidate_id">
              <td class="mono">{{ i.candidate_id }}</td>
              <td>
                <span class="pill" :class="STATE[i.status].pill">{{ STATE[i.status].label }}</span>
              </td>
              <td>
                <BaseButton
                  variant="secondary"
                  :disabled="reissuing"
                  :aria-label="`Resend link to ${i.candidate_id}`"
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
