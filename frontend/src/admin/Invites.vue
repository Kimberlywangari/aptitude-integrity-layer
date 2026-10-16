<script setup lang="ts">
import { useMutation } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import type { Invite, InvitesResponse } from '../lib/adminTypes'
import { invitesToCsv } from '../lib/csv'
import { formatInviteCode } from '../lib/inviteCode'

const MAX_INVITES = 500

const count = ref(20)
const invites = ref<Invite[] | null>(null)

const {
  mutate: generate,
  isPending,
  isError,
} = useMutation({
  mutationFn: (n: number) =>
    api<InvitesResponse>('/api/admin/invites', { method: 'POST', body: { count: n } }),
  onSuccess: (data) => {
    invites.value = data.invites
  },
})

const valid = computed(
  () => Number.isFinite(count.value) && count.value >= 1 && count.value <= MAX_INVITES,
)

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
</script>

<template>
  <h1>Invitations</h1>
  <p>
    Each candidate gets one personal code. Send them their own link from the CSV, or just the code:
    they type it on the first screen. Candidate IDs are opaque: keep the list of who holds which ID
    on your side, it is never stored here.
  </p>

  <form class="panel" @submit.prevent="generate(Math.round(count))">
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
</template>
