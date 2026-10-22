<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import SuccessMark from '../components/SuccessMark.vue'
import { api, pathForError } from '../lib/api'
import type { FinishRequest, FinishResponse } from '../lib/api'
import { stopRecording } from '../lib/recording'
import { CANDIDATE_PATH } from '../lib/routes'
import { endTestRuntime } from '../lib/runtime'
import { getSessionId } from '../lib/session'
import { SELF_REPORT_NOTE_HINT, SELF_REPORT_NOTE_LABEL, SELF_REPORT_QUESTION } from './copy'

const router = useRouter()
const sessionId = getSessionId()
const summary = ref<FinishResponse | null>(null)
const issues = ref<boolean | null>(null)
const note = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

const canSend = computed(() => issues.value !== null)

// Finishing is idempotent, so this is safe on every visit and after time-up.
onMounted(async () => {
  if (!sessionId) {
    await router.replace(CANDIDATE_PATH)
    return
  }
  // The recording stops first, so its last chunk is counted and the server is told the true total.
  // After a reload there is nothing running to stop, and the total comes from what was kept.
  const chunks = await stopRecording()
  try {
    summary.value = await api<FinishResponse>(`/api/session/${sessionId}/finish`, {
      method: 'POST',
      // omitted when nothing was recorded, so the server is not told "nothing is expected"
      ...(chunks > 0 ? { body: { chunks_total: chunks } satisfies FinishRequest } : {}),
    })
  } catch (e) {
    const route = pathForError(e)
    if (route && route !== '/done') await router.replace(route)
  }
  await endTestRuntime() // the heartbeat and the watchers stop, and the whole log is sent
})

async function submit() {
  if (!sessionId || issues.value === null) return
  busy.value = true
  error.value = null
  try {
    await api(`/api/session/${sessionId}/self-report`, {
      method: 'POST',
      body: { had_technical_issues: issues.value, note: note.value.trim() || null },
    })
    // Recording upload carries on from here; the candidate waits for it on /uploading.
    await router.replace('/uploading')
  } catch {
    error.value = 'Could not save that. Please try again.'
    busy.value = false
  }
}
</script>

<template>
  <main class="page narrow">
    <BrandMark />
    <div class="head rise">
      <SuccessMark />
      <div>
        <h1>Test finished</h1>
        <p v-if="summary" class="lead">
          You answered {{ summary.answered }} of {{ summary.total }} questions.
        </p>
      </div>
    </div>

    <form class="card rise" style="--d: 60ms" @submit.prevent="submit">
      <fieldset>
        <legend>{{ SELF_REPORT_QUESTION }}</legend>
        <label class="option">
          <input v-model="issues" type="radio" name="issues" :value="false" />
          <span class="mark" aria-hidden="true" />
          <span>No</span>
        </label>
        <label class="option">
          <input v-model="issues" type="radio" name="issues" :value="true" />
          <span class="mark" aria-hidden="true" />
          <span>Yes</span>
        </label>
      </fieldset>

      <template v-if="issues === true">
        <label class="field" for="note">{{ SELF_REPORT_NOTE_LABEL }}</label>
        <textarea id="note" v-model="note" :maxlength="300" rows="4" />
        <p class="muted">{{ SELF_REPORT_NOTE_HINT }} ({{ note.length }}/300)</p>
      </template>

      <BaseButton type="submit" :busy="busy" :disabled="!canSend">
        {{ busy ? 'Sending...' : 'Send' }}
      </BaseButton>
      <Banner v-if="error" tone="bad" role="alert"><p>{{ error }}</p></Banner>
    </form>

    <p><RouterLink to="/complaint">Camera or upload trouble? Tell us.</RouterLink></p>
  </main>
</template>

<style scoped>
.head {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1.25rem;
}

.head h1 {
  margin-bottom: 0.15rem;
}

.head .lead {
  margin: 0;
}
</style>
