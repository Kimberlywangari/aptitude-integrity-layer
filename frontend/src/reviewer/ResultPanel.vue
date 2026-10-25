<script setup lang="ts">
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import { getStaff } from '../lib/staffSession'
import type { ResultPanel, ResultRequest } from '../lib/reviewTypes'
import { BLOCKED_BY, EMAIL_PILLS, RESULT_NOTE, STATUS_PILLS } from './copy'

// The result of the test, for the candidate: you pick pass or fail, and the system sends the email.
// Open to a reviewer and to an admin alike (the server checks the role, not this page).
const props = defineProps<{ candidateId: string; panel: ResultPanel }>()

const queryClient = useQueryClient()
const isAdmin = computed(() => getStaff()?.role === 'admin')

const choice = ref<'pass' | 'fail' | ''>('')
const reasonKey = ref('')
const reasonText = ref('')
const confirming = ref(false)
const resending = ref(false)

const pill = computed(() => STATUS_PILLS[props.panel.status])
const mail = computed(() => EMAIL_PILLS[props.panel.email_state])
const blocked = computed(() => (props.panel.blocked_by ? BLOCKED_BY[props.panel.blocked_by] : null))
const typed = computed(() => reasonText.value.trim())
const reasonOk = computed(
  () =>
    choice.value === 'pass' ||
    (choice.value === 'fail' &&
      (reasonKey.value !== '' && reasonKey.value !== 'other'
        ? true
        : reasonKey.value === 'other' && typed.value.length > 0)),
)
const ready = computed(() => props.panel.can_record && choice.value !== '' && reasonOk.value)

const ERRORS: Record<string, string> = {
  review_first: BLOCKED_BY.review_first,
  already_emailed: BLOCKED_BY.already_emailed,
  no_email: BLOCKED_BY.no_email,
  not_finished: BLOCKED_BY.not_finished,
  reason_required: 'A failed candidate must be given a reason.',
  reason_too_long: 'Keep the reason to one line (200 characters).',
}
const message = (e: unknown) =>
  e instanceof ApiError ? (ERRORS[e.code] ?? 'Could not send the result.') : 'Could not send the result.'

const refresh = () =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ['candidate', props.candidateId] }),
    queryClient.invalidateQueries({ queryKey: ['outcomes'] }),
    queryClient.invalidateQueries({ queryKey: ['audit'] }),
    queryClient.invalidateQueries({ queryKey: ['overview'] }),
  ])

const {
  mutate: send,
  isPending: sending,
  error: sendError,
  reset: clearSendError,
} = useMutation({
  mutationFn: (body: ResultRequest) =>
    api<{ status: string }>(`/api/review/candidates/${encodeURIComponent(props.candidateId)}/result`, {
      method: 'POST',
      body,
    }),
  onSuccess: async () => {
    confirming.value = false
    choice.value = ''
    reasonKey.value = ''
    reasonText.value = ''
    await refresh()
  },
  onError: () => {
    confirming.value = false
  },
})

const {
  mutate: resend,
  isPending: resendBusy,
  error: resendError,
} = useMutation({
  mutationFn: () =>
    api<void>(`/api/review/candidates/${encodeURIComponent(props.candidateId)}/result/resend`, {
      method: 'POST',
      body: { confirm: true },
    }),
  onSuccess: async () => {
    resending.value = false
    await refresh()
  },
})

// Admin only: note that a candidate who failed has written to ask for a second look.
const { mutate: markAppeal, isPending: appealBusy } = useMutation({
  mutationFn: (under: boolean) =>
    api<void>(`/api/admin/candidates/${encodeURIComponent(props.candidateId)}/appeal`, {
      method: 'POST',
      body: { under_appeal: under },
    }),
  onSuccess: refresh,
})

function ask() {
  if (!ready.value) return
  clearSendError()
  confirming.value = true
}
function confirm() {
  if (choice.value === '') return
  send({
    result: choice.value,
    ...(choice.value === 'fail'
      ? reasonKey.value === 'other'
        ? { reason_key: 'other', reason_text: typed.value }
        : { reason_key: reasonKey.value }
      : {}),
  })
}
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '')
</script>

<template>
  <section class="panel" aria-labelledby="result-heading">
    <div class="row-between">
      <h2 id="result-heading">Result and email</h2>
      <span class="pill" :class="pill.tone">{{ pill.label }}</span>
    </div>

    <p class="facts">
      Score <strong>{{ panel.score }} of {{ panel.total }}</strong>
      <template v-if="panel.pass_mark !== null"> · pass mark {{ panel.pass_mark }}</template>
      <template v-else> · no pass mark set for this sitting</template>
    </p>

    <template v-if="panel.result">
      <p>
        <strong>{{ panel.result === 'pass' ? 'Passed' : 'Did not pass' }}</strong>
        <template v-if="panel.basis === 'score'"> because the score was below the pass mark.</template>
        <template v-else>, decided by {{ panel.decided_by }}.</template>
        <template v-if="panel.reason && panel.basis === 'review'"> Reason given: {{ panel.reason }}</template>
      </p>
      <p class="muted">
        Email: <span class="pill" :class="mail.tone">{{ mail.label }}</span>
        <template v-if="panel.decided_at"> · recorded {{ when(panel.decided_at) }}</template>
      </p>
      <div v-if="panel.email_state === 'sent' || panel.email_state === 'failed'" class="actions">
        <template v-if="resending">
          <span role="alert">Send this email again? The candidate will get a second copy.</span>
          <BaseButton :busy="resendBusy" @click="resend()">Yes, send again</BaseButton>
          <BaseButton variant="secondary" @click="resending = false">Cancel</BaseButton>
        </template>
        <BaseButton v-else variant="secondary" @click="resending = true">Send again</BaseButton>
      </div>
      <Banner v-if="resendError" tone="bad" role="alert"><p>Could not send it again.</p></Banner>
      <div v-if="isAdmin && panel.result === 'fail'" class="actions">
        <BaseButton
          v-if="panel.status !== 'under_appeal'"
          variant="secondary"
          :busy="appealBusy"
          @click="markAppeal(true)"
        >
          Mark as under appeal
        </BaseButton>
        <BaseButton v-else variant="secondary" :busy="appealBusy" @click="markAppeal(false)">
          Appeal closed
        </BaseButton>
      </div>
    </template>

    <template v-else>
      <p v-if="panel.basis === null && panel.status === 'failed_score'" class="muted">
        The score is below the pass mark. When the sitting closes the system will send the candidate a
        short email saying so, unless you pass them first.
      </p>
      <Banner v-if="blocked" tone="info" role="status"><p>{{ blocked }}</p></Banner>

      <form v-if="panel.can_record" @submit.prevent="ask">
        <p class="muted">{{ RESULT_NOTE }}</p>
        <fieldset>
          <legend>Result</legend>
          <div class="outcomes">
            <label class="option">
              <input v-model="choice" type="radio" name="result" value="pass" />
              <span class="mark" aria-hidden="true" />
              <span>Pass</span>
            </label>
            <label class="option">
              <input v-model="choice" type="radio" name="result" value="fail" />
              <span class="mark" aria-hidden="true" />
              <span>Do not pass</span>
            </label>
          </div>
        </fieldset>

        <template v-if="choice === 'fail'">
          <label class="field" for="result-reason">Reason the candidate is told</label>
          <select id="result-reason" v-model="reasonKey">
            <option value="" disabled>Choose a reason</option>
            <option v-for="r in panel.reasons" :key="r.key" :value="r.key">{{ r.text }}</option>
            <option value="other">Something else (write one line)</option>
          </select>
          <template v-if="reasonKey === 'other'">
            <label class="field" for="result-text">One line, in plain words</label>
            <input id="result-text" v-model="reasonText" maxlength="200" autocomplete="off" />
            <p class="muted">{{ typed.length }}/200</p>
          </template>
        </template>

        <div class="actions">
          <template v-if="confirming">
            <span role="alert">
              Send the {{ choice === 'pass' ? 'pass' : 'not-passed' }} email now? It cannot be taken back.
            </span>
            <BaseButton type="button" :busy="sending" @click="confirm">Yes, send</BaseButton>
            <BaseButton type="button" variant="secondary" @click="confirming = false">Cancel</BaseButton>
          </template>
          <BaseButton v-else type="submit" :disabled="!ready">Send result email</BaseButton>
        </div>
      </form>
      <Banner v-if="sendError" tone="bad" role="alert"><p>{{ message(sendError) }}</p></Banner>
    </template>
  </section>
</template>
