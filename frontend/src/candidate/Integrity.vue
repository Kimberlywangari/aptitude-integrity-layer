<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import Icon from '../components/Icon.vue'
import { api, ApiError, pathForError } from '../lib/api'
import type { BeginResponse, PaperResponse } from '../lib/api'
import { prepareRecording } from '../lib/runtime'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import {
  INTEGRITY_CHECKBOX,
  INTEGRITY_POINTS,
  INTEGRITY_TITLE,
  PAPER_FAILED,
  PAPER_PREPARING,
  PAPER_PREPARING_NOTE,
  PAPER_RETRY,
  PAPER_SLOW,
  PAPER_SLOW_RETRY,
  RECORDING_PROBLEMS,
  RECORDING_STARTING,
} from './copy'

const router = useRouter()
const sessionId = getSessionId()
const agreed = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

// An AI sitting writes this candidate's questions in the background. Until they exist the test
// cannot begin, so the page asks every couple of seconds and holds the button back. A paper
// that is already built answers `ready` the first time, and the page never shows a wait.
const PAPER_POLL_MS = 2000
const paper = ref<PaperResponse | null>(null)
let paperTimer: number | undefined
const preparing = computed(() => paper.value?.status === 'pending')
const paperFailed = computed(() => paper.value?.status === 'failed')
// Waited past the limit (the server decides how long): the candidate may ask for the questions again.
const paperSlow = computed(() => preparing.value && paper.value?.can_retry === true)

async function checkPaper(retry = false) {
  if (!sessionId) return
  window.clearTimeout(paperTimer)
  try {
    paper.value = await api<PaperResponse>(
      `/api/session/${sessionId}/paper${retry ? '/retry' : ''}`,
      retry ? { method: 'POST' } : {},
    )
  } catch (e) {
    const route = pathForError(e)
    if (route && route !== '/integrity') {
      await router.replace(route)
      return
    }
  }
  // a failed ask is tried again too: a dropped connection should not strand the candidate
  if (paper.value === null || paper.value.status === 'pending') {
    paperTimer = window.setTimeout(() => void checkPaper(), PAPER_POLL_MS)
  }
}

onMounted(() => {
  if (!sessionId) void router.replace(CANDIDATE_PATH)
  else void checkPaper()
})

onBeforeUnmount(() => window.clearTimeout(paperTimer))

const starting = ref(false)

async function begin() {
  if (!sessionId) return
  busy.value = true
  error.value = null
  try {
    // Recording comes first. The test begins only once a real recording is safely with the server,
    // so a candidate is never timed while nothing is being recorded.
    starting.value = true
    const prepared = await prepareRecording(sessionId)
    starting.value = false
    if (prepared !== 'ready') {
      error.value = RECORDING_PROBLEMS[prepared]
      busy.value = false
      return
    }

    // The server starts the timer now, not when the page was opened.
    await api<BeginResponse>(`/api/session/${sessionId}/begin`, {
      method: 'POST',
      body: { accepted: true },
    })
    await router.replace('/test')
  } catch (e) {
    starting.value = false
    const route = pathForError(e)
    if (route && route !== '/integrity') await router.replace(route)
    else if (e instanceof ApiError && e.code === 'paper_not_ready') {
      // the questions are not there yet: the banner below says so, and the page keeps asking
      void checkPaper()
    } else if (e instanceof ApiError && e.code === 'precheck_required') {
      // the server has not seen a usable recording yet (the camera check cannot fix that)
      error.value = RECORDING_PROBLEMS.not_confirmed
    } else error.value = 'Something went wrong. Please try again.'
    busy.value = false
  }
}
</script>

<template>
  <main class="page">
    <BrandMark />
    <h1>{{ INTEGRITY_TITLE }}</h1>
    <p v-if="paper?.candidate_name" id="whose-test" class="lead">
      You are taking this test as <strong>{{ paper.candidate_name }}</strong>. If that is not you, stop
      here and tell the person who invited you.
    </p>

    <section class="card rise">
      <ul class="statement">
        <li v-for="point in INTEGRITY_POINTS" :key="point">
          <span class="tick"><Icon name="check" size="0.95rem" /></span>
          <span>{{ point }}</span>
        </li>
      </ul>
    </section>

    <label class="check rise" style="--d: 50ms">
      <input v-model="agreed" type="checkbox" />
      <span class="mark" aria-hidden="true" />
      <span>{{ INTEGRITY_CHECKBOX }}</span>
    </label>

    <Banner v-if="preparing" tone="info" role="status">
      <p>
        <strong>{{ PAPER_PREPARING }}</strong>
        <span v-if="paper && paper.total > 0">: {{ paper.written }} of {{ paper.total }} ready</span>
      </p>
      <p class="muted">{{ PAPER_PREPARING_NOTE }}</p>
      <template v-if="paperSlow">
        <p>{{ PAPER_SLOW }}</p>
        <BaseButton variant="secondary" @click="checkPaper(true)">{{ PAPER_SLOW_RETRY }}</BaseButton>
      </template>
    </Banner>
    <Banner v-else-if="paperFailed" tone="bad" role="alert">
      <p>{{ PAPER_FAILED }}</p>
      <BaseButton variant="secondary" @click="checkPaper(true)">{{ PAPER_RETRY }}</BaseButton>
    </Banner>

    <p class="muted">Your time starts as soon as you press the button below.</p>
    <BaseButton size="lg" :disabled="!agreed || preparing || paperFailed" :busy="busy" @click="begin">
      {{ starting ? RECORDING_STARTING : busy ? 'Starting...' : 'I agree, start the test' }}
    </BaseButton>

    <Banner v-if="error" tone="bad" role="alert"><p>{{ error }}</p></Banner>
  </main>
</template>

<style scoped>
.statement {
  display: grid;
  gap: 0.8rem;
  padding: 0;
  margin: 0;
  list-style: none;
}

.statement li {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
}

.tick {
  display: grid;
  flex: none;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  margin-top: 0.05rem;
  color: var(--ok);
  background: var(--ok-tint);
  border-radius: 50%;
}
</style>
