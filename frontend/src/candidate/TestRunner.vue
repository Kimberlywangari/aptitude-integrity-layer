<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import Icon from '../components/Icon.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { useFullscreen } from '../composables/useFullscreen'
import { api, ApiError, pathForError } from '../lib/api'
import type { QuestionResponse, ResolveResponse } from '../lib/api'
import { logEvent } from '../lib/eventLog'
import { fullscreenRequired } from '../lib/features'
import { CANDIDATE_PATH } from '../lib/routes'
import { startTestRuntime } from '../lib/runtime'
import { getSessionId } from '../lib/session'
import FullscreenGate from './FullscreenGate.vue'
import MicBanner from './MicBanner.vue'
import RecordingBanner from './RecordingBanner.vue'

interface Clock {
  remaining: number // seconds left, as the server said
  syncedAt: number // performance.now() when the server said it
}

const WARN_BELOW_S = 300
const DANGER_BELOW_S = 60

const router = useRouter()
const sessionId = getSessionId()
const question = ref<QuestionResponse | null>(null)
const selected = ref<number | null>(null)
const clock = ref<Clock | null>(null)
const left = ref<number | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)

const fullscreen = useFullscreen()
let refreshing = false
let ticker: number | undefined
let lastOpened = 0 // the question already logged as opened, so a re-sync does not log it again
let runtimeStarted = false

function format(seconds: number): string {
  const whole = Math.max(0, Math.ceil(seconds))
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const timeText = computed(() => (left.value === null ? '--:--' : format(left.value)))
const timerTone = computed(() => {
  if (left.value === null) return ''
  if (left.value < DANGER_BELOW_S) return 'danger'
  if (left.value < WARN_BELOW_S) return 'warn'
  return ''
})
// While the page is not full screen the question is covered. The server clock does not stop.
const coverOn = computed(
  () => fullscreenRequired() && !fullscreen.active.value && question.value !== null,
)

function sync(remaining: number) {
  clock.value = { remaining, syncedAt: performance.now() }
  left.value = remaining // show it now; the next tick carries on from here
}

// Where to go, or a message, for any failure from the flow.
function handleError(e: unknown) {
  const route = pathForError(e)
  if (route) {
    void router.replace(route)
    return
  }
  error.value = 'Could not reach the server. Your answers so far are safe. Please try again.'
}

// The question comes from the server on every load, so a reload keeps the same question and the
// same time left.
async function load() {
  if (!sessionId) {
    await router.replace(CANDIDATE_PATH)
    return
  }
  try {
    const q = await api<QuestionResponse>(`/api/session/${sessionId}/question`)
    question.value = q
    selected.value = null
    error.value = null
    sync(q.remaining_s)
    // Only once the server has handed over a question, so a test that is already over never turns
    // the camera and the recording back on.
    if (!runtimeStarted) {
      runtimeStarted = true
      startTestRuntime(sessionId)
    }
    if (q.position !== lastOpened) {
      lastOpened = q.position
      void logEvent('question_opened', { position: q.position })
    }
  } catch (e) {
    handleError(e)
  }
}

// Countdown: counted from the server's remaining_s, re-synced on every response, never from the
// device's wall clock.
function onTick() {
  const c = clock.value
  if (!c) return
  const value = Math.max(0, c.remaining - (performance.now() - c.syncedAt) / 1000)
  left.value = value
  if (value <= 0 && !refreshing) {
    refreshing = true
    // Ask the server: it answers 410 time_up (-> /done), or re-syncs if it disagrees.
    void load().finally(() => {
      refreshing = false
    })
  }
}

// No Back: keep the page on the same history entry, and ask before a reload or close.
const keepHere = () => history.pushState(null, '', location.href)
function askBeforeLeaving(event: BeforeUnloadEvent) {
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  // The log, heartbeat, microphone watch and recording start with the first question (see load) and
  // run until the finish page ends them.
  void load()
  keepHere()
  window.addEventListener('popstate', keepHere)
  window.addEventListener('beforeunload', askBeforeLeaving)
  ticker = window.setInterval(onTick, 250)
})

onBeforeUnmount(() => {
  window.clearInterval(ticker)
  window.removeEventListener('popstate', keepHere)
  window.removeEventListener('beforeunload', askBeforeLeaving)
})

async function resolve(kind: 'answer' | 'skip') {
  const q = question.value
  if (!q || !sessionId || busy.value) return
  if (kind === 'answer' && selected.value === null) return
  busy.value = true
  error.value = null
  try {
    const result = await api<ResolveResponse>(`/api/session/${sessionId}/${kind}`, {
      method: 'POST',
      body:
        kind === 'answer'
          ? { position: q.position, option_id: selected.value }
          : { position: q.position },
    })
    void logEvent(kind === 'answer' ? 'answered' : 'skipped', { position: q.position })
    if (result.done) {
      await router.replace('/done')
      return
    }
    sync(result.remaining_s)
    await load()
  } catch (e) {
    if (e instanceof ApiError && e.code === 'not_current') await load()
    else handleError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main v-if="!question" class="page">
    <p role="status">{{ error ?? 'Loading your question...' }}</p>
    <BaseButton v-if="error" @click="load">Try again</BaseButton>
  </main>

  <main v-else class="page test">
    <!-- inert makes everything underneath unreachable (mouse, keyboard, screen reader) while the
         cover is up. Bound as an object so the attribute is removed, not set to "false". -->
    <div v-bind="coverOn ? { inert: true } : {}">
      <header class="top">
        <div class="where">
          <span class="count">Question {{ question.position }} of {{ question.total }}</span>
          <span class="chip section">{{ question.section }}</span>
        </div>
        <div class="timer" :class="timerTone" role="timer">
          <Icon name="clock" size="1.05em" />
          <span>{{ timeText }}</span>
        </div>
      </header>
      <ProgressBar label="Test progress" :value="question.position - 1" :max="question.total" />

      <MicBanner />
      <RecordingBanner />

      <Transition name="q" mode="out-in">
        <div :key="question.position" class="qcard">
          <p id="question-text" class="question-text">{{ question.text }}</p>

          <fieldset :disabled="busy">
            <legend class="sr-only">Choose one answer</legend>
            <label v-for="option in question.options" :key="option.id" class="option">
              <input v-model="selected" type="radio" name="answer" :value="option.id" />
              <span class="mark" aria-hidden="true" />
              <span class="text">{{ option.text }}</span>
            </label>
          </fieldset>
        </div>
      </Transition>

      <div class="actions">
        <BaseButton size="lg" :busy="busy" :disabled="selected === null" @click="resolve('answer')">
          Submit
        </BaseButton>
        <BaseButton variant="secondary" size="lg" :disabled="busy" @click="resolve('skip')">
          Skip
        </BaseButton>
      </div>
      <p class="muted">You cannot come back to a question once you move on.</p>

      <Banner v-if="error" tone="bad" role="alert"><p>{{ error }}</p></Banner>
    </div>

    <Transition name="cover">
      <FullscreenGate v-if="coverOn" :time-left="timeText" />
    </Transition>
  </main>
</template>

<style scoped>
.top {
  display: flex;
  gap: 1rem;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.9rem;
}

.where {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.count {
  font-weight: 650;
  letter-spacing: -0.01em;
}

.section {
  margin: 0;
  color: var(--muted);
  text-transform: capitalize;
}

.timer {
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
  padding: 0.3rem 0.8rem;
  font-size: 1.1rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 999px;
  transition:
    color 300ms var(--ease-out),
    background-color 300ms var(--ease-out),
    border-color 300ms var(--ease-out);
}

.timer.warn {
  color: var(--warn-text);
  background: var(--warn-bg);
  border-color: var(--warn-line);
}

.timer.danger {
  color: var(--danger);
  background: var(--danger-tint);
  border-color: var(--danger);
}

.qcard {
  margin-top: 1.4rem;
}

.question-text {
  margin: 0 0 1.25rem;
  font-size: 1.2rem;
  line-height: 1.45;
  letter-spacing: -0.005em;
  /* Keep the line breaks a question carries: a passage above its question, or a list of values. */
  white-space: pre-line;
  text-wrap: pretty;
}

.actions {
  margin-top: 0.5rem;
}

.actions > * {
  flex: 1 1 8rem;
}

/* The test is used under a clock, so the question changes with a very short fade and nothing
   more. The way out is faster than the way in. */
.q-enter-active {
  transition:
    opacity 140ms var(--ease-out),
    transform 140ms var(--ease-out);
}

.q-leave-active {
  transition: opacity 70ms var(--ease-out);
}

.q-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.q-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .q-enter-from {
    transform: none;
  }
}
</style>
