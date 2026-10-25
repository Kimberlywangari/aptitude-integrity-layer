<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type { ResultsPlan } from '../lib/adminTypes'

// The result emails. A reviewer shortlists (that is the pass); an admin sends. Nothing here decides
// who passes: it only tells each person what a human already decided.
const props = defineProps<{ sittingId: number }>()

const queryClient = useQueryClient()
const key = computed(() => ['admin', 'results', props.sittingId])

const { data: plan, isError } = useQuery({
  queryKey: key,
  queryFn: () => api<ResultsPlan>(`/api/admin/sittings/${props.sittingId}/results`),
})

type Kind = 'passed' | 'not_passed'
const confirming = ref<Kind | null>(null)
const queuedNow = ref<{ kind: Kind; n: number } | null>(null)

const { mutate: send, isPending, isError: sendFailed, error: sendError } = useMutation({
  mutationFn: (kind: Kind) =>
    api<{ queued: number }>(`/api/admin/sittings/${props.sittingId}/results/send`, {
      method: 'POST',
      body: { kind },
    }),
  onSuccess: async (data, kind) => {
    queuedNow.value = { kind, n: data.queued }
    confirming.value = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: key.value }),
      queryClient.invalidateQueries({ queryKey: ['admin', 'sittings', props.sittingId] }),
      queryClient.invalidateQueries({ queryKey: ['admin', 'mail'] }),
    ])
  },
})

const sendMessage = computed(() =>
  sendError.value instanceof ApiError && sendError.value.code === 'sitting_not_closed'
    ? 'Close the sitting first.'
    : 'Could not queue the emails.',
)

const label = (kind: Kind) => (kind === 'passed' ? 'pass' : 'not-passed')
const count = (kind: Kind) => (plan.value ? (kind === 'passed' ? plan.value.passed : plan.value.not_passed) : 0)
</script>

<template>
  <section v-if="plan" class="panel" aria-labelledby="results-heading">
    <h2 id="results-heading">Result emails</h2>
    <p class="muted">
      A reviewer shortlists the people who pass. You send each person one short email: a pass email to the
      shortlisted, and, once the sitting is closed, a not-passed email to everyone else who finished. Nobody
      who did not finish is written to, and nobody is told anything about flags, video or review.
    </p>

    <ul class="facts-list">
      <li><strong>{{ plan.passed }}</strong> ready for a pass email ({{ plan.sent_passed }} already sent)</li>
      <li>
        <strong>{{ plan.not_passed }}</strong> ready for a not-passed email ({{ plan.sent_not_passed }}
        already sent)
      </li>
      <li v-if="plan.held_back.length > 0" id="held-back">
        <strong>{{ plan.held_back.length }}</strong> held back until a person decides:
        <span class="mono">{{ plan.held_back.join(', ') }}</span>
      </li>
      <li v-if="plan.did_not_finish > 0">{{ plan.did_not_finish }} did not finish and get no email</li>
      <li v-if="plan.without_email > 0">{{ plan.without_email }} have no email address on file</li>
    </ul>

    <details>
      <summary>Read the two emails</summary>
      <h3>Pass</h3>
      <p class="muted">Subject: {{ plan.preview_passed.subject }}</p>
      <pre class="email">{{ plan.preview_passed.body }}</pre>
      <h3>Not passed</h3>
      <p class="muted">Subject: {{ plan.preview_not_passed.subject }}</p>
      <pre class="email">{{ plan.preview_not_passed.body }}</pre>
      <p class="muted">The wording is in <code>backend/app/mail_templates</code>.</p>
    </details>

    <div v-for="kind in (['passed', 'not_passed'] as Kind[])" :key="kind" class="send-row">
      <template v-if="confirming === kind">
        <p role="alert">
          Send {{ count(kind) }} {{ label(kind) }} {{ count(kind) === 1 ? 'email' : 'emails' }} now? An email
          cannot be taken back.
        </p>
        <BaseButton :busy="isPending" @click="send(kind)">Yes, send</BaseButton>
        <BaseButton variant="secondary" @click="confirming = null">Cancel</BaseButton>
      </template>
      <BaseButton
        v-else
        variant="secondary"
        :disabled="count(kind) === 0 || (kind === 'not_passed' && !plan.sitting_closed)"
        @click="confirming = kind"
      >
        Send {{ label(kind) }} emails ({{ count(kind) }})
      </BaseButton>
      <span v-if="kind === 'not_passed' && !plan.sitting_closed" class="muted">
        Close the sitting first.
      </span>
    </div>

    <Banner v-if="queuedNow" tone="good" role="status">
      <p>
        {{ queuedNow.n }} {{ label(queuedNow.kind) }} {{ queuedNow.n === 1 ? 'email is' : 'emails are' }}
        queued and will go out in a moment.
      </p>
    </Banner>
    <Banner v-if="sendFailed" tone="bad" role="alert"><p>{{ sendMessage }}</p></Banner>
  </section>
  <Banner v-else-if="isError" tone="bad" role="alert"><p>Could not load the result emails.</p></Banner>
</template>

<style scoped>
.facts-list {
  margin: 0.75rem 0;
  padding-left: 1.1rem;
}

.send-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  margin: 0.6rem 0;
}

.email {
  padding: 0.75rem 1rem;
  font-family: inherit;
  white-space: pre-wrap;
  background: var(--surface-2);
  border-radius: 8px;
}
</style>
