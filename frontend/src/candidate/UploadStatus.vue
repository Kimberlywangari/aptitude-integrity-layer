<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import ProgressBar from '../components/ProgressBar.vue'
import SuccessMark from '../components/SuccessMark.vue'
import { api } from '../lib/api'
import type { ManifestResponse } from '../lib/api'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import {
  FINISHED_BODY,
  FINISHED_TITLE,
  UPLOAD_DONE,
  UPLOAD_KEEP_OPEN,
  UPLOAD_STUCK,
  UPLOAD_TITLE,
} from './copy'

const POLL_MS = 3000
const FAILURES_BEFORE_FINISH = 3
const STALLED_AFTER_MS = 60_000

const router = useRouter()
const sessionId = getSessionId()
const manifest = ref<ManifestResponse | null>(null)
const failures = ref(0)
const stalled = ref(false)
const finished = ref(false)

let lastReceived = -1
let lastChangeAt = 0
let timer: number | undefined
let stopped = false

async function poll() {
  try {
    const next = await api<ManifestResponse>(`/api/chunks/${sessionId}/manifest`)
    if (stopped) return
    manifest.value = next
    failures.value = 0
    if (next.received !== lastReceived) {
      lastReceived = next.received
      lastChangeAt = performance.now()
      stalled.value = false
    } else if (!next.complete && performance.now() - lastChangeAt > STALLED_AFTER_MS) {
      stalled.value = true
    }
    if (!next.complete) timer = window.setTimeout(() => void poll(), POLL_MS)
  } catch {
    if (stopped) return
    failures.value += 1
    timer = window.setTimeout(() => void poll(), POLL_MS)
  }
}

// Closing the tab while parts are still unsent would lose them from the server's side, so ask first.
function warnBeforeClosing(event: BeforeUnloadEvent) {
  if (manifest.value?.complete || finished.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  if (!sessionId) {
    await router.replace(CANDIDATE_PATH)
    return
  }
  lastChangeAt = performance.now()
  window.addEventListener('beforeunload', warnBeforeClosing)
  void poll()
})

onBeforeUnmount(() => {
  stopped = true
  window.clearTimeout(timer)
  window.removeEventListener('beforeunload', warnBeforeClosing)
})

const complete = computed(() => manifest.value?.complete === true)
const canFinishAnyway = computed(
  () => !complete.value && (failures.value >= FAILURES_BEFORE_FINISH || stalled.value),
)
const percent = computed(() =>
  manifest.value && manifest.value.expected
    ? Math.round((manifest.value.received / manifest.value.expected) * 100)
    : null,
)
</script>

<template>
  <main class="page narrow">
    <BrandMark />

    <template v-if="finished">
      <div class="done rise">
        <SuccessMark />
        <div>
          <h1>{{ FINISHED_TITLE }}</h1>
          <p class="lead">{{ FINISHED_BODY }}</p>
        </div>
      </div>
    </template>

    <template v-else>
      <h1>{{ UPLOAD_TITLE }}</h1>

      <section class="card rise">
        <Banner v-if="complete" tone="good" role="status"><p>{{ UPLOAD_DONE }}</p></Banner>
        <p v-else>{{ UPLOAD_KEEP_OPEN }}</p>

        <template v-if="manifest && manifest.expected !== null">
          <ProgressBar
            label="Upload progress"
            :value="manifest.received"
            :max="manifest.expected"
            :tone="complete ? 'ok' : 'accent'"
          />
          <p class="muted detail">
            Uploaded {{ manifest.received }} of {{ manifest.expected }} parts
            <template v-if="percent !== null">({{ percent }}%)</template>.
          </p>
        </template>
        <p v-if="!manifest && failures === 0" role="status">Checking your upload...</p>
        <p v-if="failures > 0 && !complete" role="status" class="muted">
          Could not reach the server. Trying again.
        </p>

        <Banner v-if="canFinishAnyway" tone="bad" role="alert"><p>{{ UPLOAD_STUCK }}</p></Banner>

        <div class="actions">
          <BaseButton v-if="complete" @click="finished = true">Finish</BaseButton>
          <BaseButton v-if="canFinishAnyway" variant="secondary" @click="finished = true">
            Finish anyway
          </BaseButton>
        </div>
      </section>

      <p><RouterLink to="/complaint">Something went wrong? Tell us.</RouterLink></p>
    </template>
  </main>
</template>

<style scoped>
.detail {
  margin: 0.5rem 0 1rem;
}

.done {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.done h1 {
  margin-bottom: 0.15rem;
}

.done .lead {
  margin: 0;
}
</style>
