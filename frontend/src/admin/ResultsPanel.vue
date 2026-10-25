<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { RouterLink } from 'vue-router'
import Banner from '../components/Banner.vue'
import { api } from '../lib/api'
import type { ResultsPlan } from '../lib/adminTypes'

// Where the result emails of this sitting stand. Nothing is sent from here: a reviewer or an admin
// records each result on the candidate's page (or passes several from the Outcomes list), and the
// email goes at that moment. A low score is turned down by the pass mark when the sitting closes.
const props = defineProps<{ sittingId: number }>()

const {
  data: plan,
  isError,
} = useQuery({
  queryKey: ['admin', 'results', props.sittingId],
  queryFn: () => api<ResultsPlan>(`/api/admin/sittings/${props.sittingId}/results`),
})
</script>

<template>
  <section v-if="plan" class="panel" aria-labelledby="results-heading">
    <h2 id="results-heading">Result emails</h2>
    <p class="muted">
      Each person gets one email: a pass, a short note that their score was below the pass mark, or, after
      a person has reviewed the sitting, a note with the reason and how to appeal. Nobody who did not
      finish is written to. Results are recorded on the
      <RouterLink to="/outcomes">Outcomes</RouterLink> page.
    </p>

    <ul class="facts-list">
      <li>
        <strong>{{ plan.sent_passed }}</strong> pass {{ plan.sent_passed === 1 ? 'email' : 'emails' }} sent,
        <strong>{{ plan.sent_not_passed }}</strong> not-passed
        {{ plan.sent_not_passed === 1 ? 'email' : 'emails' }} sent
      </li>
      <li v-if="plan.queued > 0"><strong>{{ plan.queued }}</strong> on the way</li>
      <li v-if="plan.failed > 0" id="failed-mail">
        <strong>{{ plan.failed }}</strong> could not be sent. Retry them from the
        <RouterLink to="/admin/invites">Invitations</RouterLink> page.
      </li>
      <li v-if="plan.held_back.length > 0" id="held-back">
        <strong>{{ plan.held_back.length }}</strong> finished and waiting for a result:
        <span class="mono">{{ plan.held_back.join(', ') }}</span>
      </li>
      <li v-if="plan.did_not_finish > 0">{{ plan.did_not_finish }} did not finish and get no email</li>
      <li v-if="plan.without_email > 0">{{ plan.without_email }} have no email address on file</li>
    </ul>

    <details>
      <summary>Read the three emails</summary>
      <h3>Passed</h3>
      <p class="muted">Subject: {{ plan.preview_passed.subject }}</p>
      <pre class="email">{{ plan.preview_passed.body }}</pre>
      <h3>Not passed: score below the pass mark</h3>
      <p class="muted">Subject: {{ plan.preview_not_passed.subject }}</p>
      <pre class="email">{{ plan.preview_not_passed.body }}</pre>
      <h3>Not passed: after a person reviewed the sitting</h3>
      <p class="muted">Subject: {{ plan.preview_not_passed_review.subject }}</p>
      <pre class="email">{{ plan.preview_not_passed_review.body }}</pre>
      <p class="muted">The wording is in <code>backend/app/mail_templates</code>.</p>
    </details>
  </section>
  <Banner v-else-if="isError" tone="bad" role="alert"><p>Could not load the result emails.</p></Banner>
</template>

<style scoped>
.facts-list {
  margin: 0.75rem 0;
  padding-left: 1.1rem;
}

.email {
  padding: 0.75rem 1rem;
  font-family: inherit;
  white-space: pre-wrap;
  background: var(--surface-2);
  border-radius: 8px;
}
</style>
