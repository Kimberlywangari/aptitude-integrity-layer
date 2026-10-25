<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import type { PassMarkPreview } from '../lib/adminTypes'

// The pass mark: how many correct answers pass. A low score gets a short rejection email when the
// sitting is closed. Changing the mark is previewed first, so nobody is surprised by who it moves.
const props = defineProps<{ sittingId: number; passMark: number | null; questionCount: number }>()

const queryClient = useQueryClient()
const typed = ref(props.passMark === null ? '' : String(props.passMark))
watch(
  () => props.passMark,
  (value) => {
    typed.value = value === null ? '' : String(value)
  },
)

const wanted = computed<number | null | 'bad'>(() => {
  const text = typed.value.trim()
  if (text === '') return null
  const n = Number(text)
  return Number.isInteger(n) && n >= 1 && n <= props.questionCount ? n : 'bad'
})
const changed = computed(() => wanted.value !== 'bad' && wanted.value !== props.passMark)

const asked = ref(false)
const { data: preview, isPending: previewing } = useQuery({
  queryKey: computed(() => ['admin', 'pass-mark', props.sittingId, wanted.value]),
  queryFn: () => {
    const value = wanted.value === null || wanted.value === 'bad' ? '' : `?value=${wanted.value}`
    return api<PassMarkPreview>(`/api/admin/sittings/${props.sittingId}/pass-mark/preview${value}`)
  },
  enabled: computed(() => asked.value && wanted.value !== 'bad'),
  gcTime: 0,
})

const saved = ref<{ mark: number | null; queued: number } | null>(null)
const {
  mutate: save,
  isPending: saving,
  isError: failed,
} = useMutation({
  mutationFn: () =>
    api<{ pass_mark: number | null; queued: number }>(`/api/admin/sittings/${props.sittingId}/pass-mark`, {
      method: 'POST',
      body: { pass_mark: wanted.value === 'bad' ? null : wanted.value },
    }),
  onSuccess: async (done) => {
    saved.value = { mark: done.pass_mark, queued: done.queued }
    asked.value = false
    await queryClient.invalidateQueries({ queryKey: ['admin'] })
    await queryClient.invalidateQueries({ queryKey: ['outcomes'] })
  },
})

function check() {
  saved.value = null
  if (changed.value) asked.value = true
}
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const errorText = computed(() => (failed.value ? 'Could not change the pass mark.' : null))
</script>

<template>
  <section class="panel" aria-labelledby="pass-mark-heading">
    <h2 id="pass-mark-heading">Pass mark</h2>
    <p class="muted">
      The number of correct answers (out of {{ questionCount }}) that passes. When the sitting is closed,
      anyone who finished below it is sent a short email saying so, with their score and the mark. Flags
      are never part of this. Leave it empty to turn it off.
    </p>
    <p>
      <strong v-if="passMark !== null">Now: {{ passMark }} of {{ questionCount }}</strong>
      <strong v-else>Now: not set</strong>
    </p>

    <form class="actions" @submit.prevent="check">
      <label class="field" for="pass-mark">Pass mark</label>
      <input
        id="pass-mark"
        v-model="typed"
        inputmode="numeric"
        autocomplete="off"
        :aria-invalid="wanted === 'bad'"
        @input="asked = false"
      />
      <BaseButton type="submit" variant="secondary" :disabled="!changed">See what it would change</BaseButton>
    </form>
    <p v-if="wanted === 'bad'" class="muted" role="alert">
      Use a whole number from 1 to {{ questionCount }}, or leave it empty.
    </p>

    <template v-if="asked && wanted !== 'bad'">
      <p v-if="previewing" role="status">Counting...</p>
      <div v-else-if="preview" class="stack">
        <p role="status">
          <template v-if="preview.newly_below === 0 && preview.no_longer_below === 0">
            Nobody who can still be moved would change.
          </template>
          <template v-else>
            {{ plural(preview.newly_below, 'candidate', 'candidates') }} would be below the mark
            <template v-if="preview.no_longer_below > 0">
              and {{ plural(preview.no_longer_below, 'candidate', 'candidates') }} would stop being below it
            </template>.
          </template>
          Anyone already emailed, and anyone a person has decided, is left alone.
          <template v-if="preview.sitting_closed && preview.emails_now > 0">
            This sitting is closed, so {{ plural(preview.emails_now, 'rejection email goes', 'rejection emails go') }}
            out now and cannot be taken back.
          </template>
          <template v-else-if="!preview.sitting_closed">
            This sitting is open, so nothing is sent until you close it.
          </template>
        </p>
        <div class="actions">
          <BaseButton :busy="saving" @click="save()">
            {{ wanted === null ? 'Turn the pass mark off' : `Set the pass mark to ${wanted}` }}
          </BaseButton>
          <BaseButton variant="secondary" @click="asked = false">Cancel</BaseButton>
        </div>
      </div>
    </template>

    <Banner v-if="saved" tone="good" role="status">
      <p>
        <template v-if="saved.mark === null">The pass mark is off.</template>
        <template v-else>The pass mark is {{ saved.mark }}.</template>
        <template v-if="saved.queued > 0">
          {{ plural(saved.queued, 'rejection email is', 'rejection emails are') }} on the way.
        </template>
      </p>
    </Banner>
    <Banner v-if="errorText" tone="bad" role="alert"><p>{{ errorText }}</p></Banner>
  </section>
</template>
