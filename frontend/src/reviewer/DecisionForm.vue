<script setup lang="ts">
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import { MIN_REASON_CHARS } from '../lib/reviewTypes'
import type { DecisionOutcome, DecisionRequest } from '../lib/reviewTypes'
import { OUTCOME_LABELS } from './copy'

const ERRORS: Record<string, string> = {
  reason_too_short: `The reason must be at least ${MIN_REASON_CHARS} characters.`,
  invalid_outcome: 'Choose one of the outcomes.',
}

const props = defineProps<{ sessionId: string; candidateId: string }>()

const queryClient = useQueryClient()
const outcome = ref<DecisionOutcome | ''>('')
const reason = ref('')
const confirmed = ref(false)
const saved = ref(false)

const {
  mutate: save,
  isPending,
  error,
} = useMutation({
  mutationFn: (body: DecisionRequest) =>
    api<{ decided_at: string }>('/api/review/decisions', { method: 'POST', body }),
  onSuccess: async () => {
    saved.value = true
    outcome.value = ''
    reason.value = ''
    confirmed.value = false
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['candidate', props.candidateId] }),
      queryClient.invalidateQueries({ queryKey: ['queue'] }),
      queryClient.invalidateQueries({ queryKey: ['candidates'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
      queryClient.invalidateQueries({ queryKey: ['outcomes'] }),
      queryClient.invalidateQueries({ queryKey: ['audit'] }),
    ])
  },
})

const trimmed = computed(() => reason.value.trim())
const valid = computed(
  () => outcome.value !== '' && trimmed.value.length >= MIN_REASON_CHARS && confirmed.value,
)
const message = computed(() => {
  if (!error.value) return null
  return error.value instanceof ApiError
    ? (ERRORS[error.value.code] ?? 'Could not save the decision. Please try again.')
    : 'Could not save the decision. Please try again.'
})
const outcomes = Object.keys(OUTCOME_LABELS) as DecisionOutcome[]

function submit() {
  if (!valid.value || outcome.value === '') return
  saved.value = false
  save({ session_id: props.sessionId, outcome: outcome.value, reason: trimmed.value })
}
</script>

<template>
  <form class="panel" @submit.prevent="submit">
    <h2>Your decision</h2>
    <fieldset>
      <legend>Outcome</legend>
      <div class="outcomes">
        <label v-for="value in outcomes" :key="value" class="option">
          <input v-model="outcome" type="radio" name="outcome" :value="value" />
          <span class="mark" aria-hidden="true" />
          <span>{{ OUTCOME_LABELS[value] }}</span>
        </label>
      </div>
    </fieldset>

    <label class="field" for="reason">Reason (required, at least {{ MIN_REASON_CHARS }} characters)</label>
    <textarea id="reason" v-model="reason" rows="4" />
    <p class="muted">{{ trimmed.length }} characters</p>

    <label class="check">
      <input v-model="confirmed" type="checkbox" />
      <span class="mark" aria-hidden="true" />
      <span>I have looked at the evidence and this reason is mine.</span>
    </label>

    <BaseButton type="submit" :disabled="!valid" :busy="isPending">
      {{ isPending ? 'Saving...' : 'Record decision' }}
    </BaseButton>

    <Banner v-if="saved" tone="good" role="status"><p>Decision recorded.</p></Banner>
    <Banner v-if="message" tone="bad" role="alert"><p>{{ message }}</p></Banner>
  </form>
</template>
