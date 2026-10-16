<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import Icon from '../components/Icon.vue'
import LevelMeter from '../components/LevelMeter.vue'
import ProgressBar from '../components/ProgressBar.vue'
import SuccessMark from '../components/SuccessMark.vue'
import { useFullscreen } from '../composables/useFullscreen'
import { api, pathForError } from '../lib/api'
import type { PrecheckRequest, PrecheckResponse } from '../lib/api'
import { captureProblem, detectBrowser, isSupportedBrowser } from '../lib/browser'
import { acquireDevices, classifyDeviceError } from '../lib/devices'
import type { DeviceErrorKind, DeviceHandle } from '../lib/devices'
import { fullscreenRequired, micCheckEnabled } from '../lib/features'
import { INITIAL_MIC_CHECK, stepMicCheck } from '../lib/micCheck'
import type { MicCheckState } from '../lib/micCheck'
import { combine, queryPermission, watchPermission } from '../lib/permissions'
import type { PermissionState } from '../lib/permissions'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import StepCard from './StepCard.vue'
import {
  CAPTURE_PROBLEMS,
  DEVICE_ERRORS,
  DEVICE_NOTICE_CHECKBOX,
  DEVICE_NOTICE_POINTS,
  FULLSCREEN_EXIT_HINT,
  FULLSCREEN_LEAD,
  FULLSCREEN_UNSUPPORTED,
  MIC_CHECK_OFF_NOTE,
  MIC_MUTED_MESSAGE,
  MIC_PROMPT,
  MIC_QUIET_MESSAGE,
  NOTIFICATIONS_CHECKBOX,
  NOTIFICATIONS_HOW,
  NOTIFICATIONS_LEAD,
  NOTIFICATIONS_NOTE,
  PERMISSION_BLOCKED_HELP,
  PERMISSION_STATE_LABELS,
  PERMISSIONS_LEAD,
  PRECHECK_LEAD,
  PRECHECK_TITLE,
  READY_LEAD,
  STEP_TITLES,
  UNSUPPORTED_BROWSER,
} from './copy'

type StepKey = 'notice' | 'notifications' | 'permissions' | 'devices' | 'fullscreen' | 'ready'
type Phase = 'idle' | 'starting' | 'live'

const TICK_MS = 100

const router = useRouter()
const sessionId = getSessionId()
const micChecked = micCheckEnabled() // false while the microphone step is switched off for testing
const needsFullscreen = fullscreenRequired()
const browser = detectBrowser()
const problem = captureProblem()
const fullscreen = useFullscreen()

const keys = computed<StepKey[]>(() => {
  const all: StepKey[] = ['notice', 'notifications', 'permissions', 'devices', 'fullscreen', 'ready']
  return needsFullscreen ? all : all.filter((k) => k !== 'fullscreen')
})
const index = ref(0)
const current = computed(() => keys.value[index.value])
const stateOf = (i: number) => (i < index.value ? 'done' : i === index.value ? 'current' : 'todo')

// ---- what the candidate has told us or done
const understood = ref(false)
const notificationsOff = ref(false)
const phase = ref<Phase>('idle')
const deviceError = ref<DeviceErrorKind | null>(null)
const cameraOk = ref(false)
const mic = ref<MicCheckState>(INITIAL_MIC_CHECK)
const level = ref(0)
const muted = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const fullscreenFailed = ref(false)
const cameraPermission = ref<PermissionState>('unknown')
const micPermission = ref<PermissionState>('unknown')

let devices: DeviceHandle | null = null
let peak = 0
let meterTimer: number | undefined
const stopWatching: (() => void)[] = []
const preview = ref<HTMLVideoElement | null>(null)

const micPassed = computed(() => mic.value.result === 'passed')
const devicesReady = computed(() => cameraOk.value && (!micChecked || micPassed.value))

const permissionKey = computed(() => {
  if (phase.value === 'starting') return 'asking'
  if (phase.value === 'live') return 'granted'
  return combine(cameraPermission.value, micPermission.value)
})
const permissionLabel = computed(() => PERMISSION_STATE_LABELS[permissionKey.value])
const permissionBlocked = computed(() => deviceError.value === 'denied' || permissionKey.value === 'denied')

onMounted(async () => {
  if (!sessionId) {
    await router.replace(CANDIDATE_PATH)
    return
  }
  // What the browser already allows for this site, and a heads-up if the candidate changes it
  // from the address bar while this page is open.
  cameraPermission.value = await queryPermission('camera')
  micPermission.value = await queryPermission('microphone')
  stopWatching.push(await watchPermission('camera', (s) => (cameraPermission.value = s)))
  stopWatching.push(await watchPermission('microphone', (s) => (micPermission.value = s)))

  // Level meter and the "say your name" check, only while that step is open.
  meterTimer = window.setInterval(() => {
    const handle = devices
    if (!handle || !micChecked || current.value !== 'devices') return
    if (mic.value.result !== 'listening') return
    const isMuted = handle.micMuted()
    muted.value = isMuted
    const reading = handle.readMicLevel()
    peak = Math.max(peak, reading.peak)
    level.value = isMuted ? 0 : reading.rms
    mic.value = stepMicCheck(mic.value, isMuted ? 0 : reading.rms, TICK_MS)
  }, TICK_MS)
})

// Release the camera and microphone when the candidate leaves this screen.
onBeforeUnmount(() => {
  window.clearInterval(meterTimer)
  stopWatching.forEach((stop) => stop())
  devices?.stop()
  devices = null
})

// Show the live picture whenever its element exists.
watch(
  preview,
  (el) => {
    if (el && devices) el.srcObject = devices.stream
  },
  { flush: 'post' },
)

// Move focus to the new step's heading, so keyboard and screen-reader users land on it.
watch(index, async () => {
  await nextTick()
  document.getElementById('step-heading')?.focus()
})

function next() {
  if (index.value < keys.value.length - 1) index.value += 1
}

function back() {
  if (index.value > 0) index.value -= 1
}

async function requestDevices() {
  phase.value = 'starting'
  deviceError.value = null
  mic.value = INITIAL_MIC_CHECK
  muted.value = false
  peak = 0
  devices?.stop()
  try {
    const handle = await acquireDevices()
    devices = handle
    cameraOk.value = handle.stream.getVideoTracks()[0]?.readyState === 'live'
    phase.value = 'live'
    next() // allowed: on to the camera and microphone check
  } catch (e) {
    devices = null
    cameraOk.value = false
    deviceError.value = classifyDeviceError(e)
    phase.value = 'idle'
    cameraPermission.value = await queryPermission('camera')
    micPermission.value = await queryPermission('microphone')
  }
}

async function goFullscreen() {
  fullscreenFailed.value = !(await fullscreen.enter())
}

async function proceed() {
  const handle = devices
  if (!sessionId || !handle) return
  busy.value = true
  error.value = null
  const body: PrecheckRequest = {
    camera_ok: cameraOk.value,
    // When the step is left out, say so: `mic_ok` then means "not checked", not "passed".
    mic_ok: micChecked && micPassed.value,
    mic_checked: micChecked,
    notifications_off_confirmed: notificationsOff.value,
    fullscreen_ok: !needsFullscreen || fullscreen.active.value,
    browser: { name: browser.name, version: browser.version },
    device_labels: { camera: handle.cameraLabel, mic: handle.micLabel },
    mic_peak: micChecked ? Number(peak.toFixed(4)) : 0,
    video_size: handle.videoSize,
  }
  try {
    const result = await api<PrecheckResponse>('/api/precheck/result', { method: 'POST', body })
    if (!result.passed) {
      error.value = 'The check did not pass. Please try again.'
      busy.value = false
      return
    }
    handle.stop()
    devices = null
    await router.replace('/integrity')
  } catch (e) {
    const route = pathForError(e)
    if (route && route !== '/precheck') await router.replace(route)
    else error.value = 'Something went wrong. Please try again.'
    busy.value = false
  }
}
</script>

<template>
  <main class="page">
    <BrandMark />
    <h1>{{ PRECHECK_TITLE }}</h1>
    <p class="lead">{{ PRECHECK_LEAD }}</p>

    <div class="progress">
      <span class="muted" aria-live="polite">Step {{ index + 1 }} of {{ keys.length }}</span>
      <ProgressBar label="Steps done" :value="index" :max="keys.length - 1" tone="ok" />
    </div>

    <ol class="steps card">
      <!-- 1. notice -->
      <StepCard :index="1" :title="STEP_TITLES.notice" :state="stateOf(keys.indexOf('notice'))" summary="Understood.">
        <Banner v-if="problem" tone="bad" role="alert"><p>{{ CAPTURE_PROBLEMS[problem] }}</p></Banner>
        <Banner v-else-if="!isSupportedBrowser(browser)" tone="warn" role="status">
          <p>{{ UNSUPPORTED_BROWSER }}</p>
        </Banner>
        <ul class="points">
          <li v-for="point in DEVICE_NOTICE_POINTS" :key="point">{{ point }}</li>
        </ul>
        <label class="check">
          <input v-model="understood" type="checkbox" />
          <span class="mark" aria-hidden="true" />
          <span>{{ DEVICE_NOTICE_CHECKBOX }}</span>
        </label>
        <BaseButton :disabled="!understood || problem !== null" @click="next">Continue</BaseButton>
      </StepCard>

      <!-- 2. notifications -->
      <StepCard
        :index="2"
        :title="STEP_TITLES.notifications"
        :state="stateOf(keys.indexOf('notifications'))"
        summary="Notifications are off."
      >
        <Banner tone="warn" icon="bell-off"><p>{{ NOTIFICATIONS_LEAD }}</p></Banner>
        <ul class="points">
          <li v-for="how in NOTIFICATIONS_HOW" :key="how">{{ how }}</li>
        </ul>
        <label class="check">
          <input v-model="notificationsOff" type="checkbox" />
          <span class="mark" aria-hidden="true" />
          <span>{{ NOTIFICATIONS_CHECKBOX }}</span>
        </label>
        <p class="muted">{{ NOTIFICATIONS_NOTE }}</p>
        <div class="actions">
          <BaseButton variant="ghost" @click="back">Back</BaseButton>
          <BaseButton :disabled="!notificationsOff" @click="next">Continue</BaseButton>
        </div>
      </StepCard>

      <!-- 3. permissions -->
      <StepCard
        :index="3"
        :title="STEP_TITLES.permissions"
        :state="stateOf(keys.indexOf('permissions'))"
        summary="Camera and microphone allowed."
      >
        <p>{{ PERMISSIONS_LEAD }}</p>
        <p class="status-line">
          <span class="pill" :class="permissionKey" role="status">
            <Icon name="camera" size="1em" /><Icon name="mic" size="1em" />
            {{ permissionLabel }}
          </span>
        </p>
        <Banner v-if="deviceError && deviceError !== 'denied'" tone="bad" role="alert">
          <p>{{ DEVICE_ERRORS[deviceError] }}</p>
        </Banner>
        <Banner v-if="permissionBlocked" tone="bad" role="alert">
          <p>{{ DEVICE_ERRORS.denied }}</p>
          <ol class="help">
            <li v-for="line in PERMISSION_BLOCKED_HELP" :key="line">{{ line }}</li>
          </ol>
        </Banner>
        <div class="actions">
          <BaseButton variant="ghost" @click="back">Back</BaseButton>
          <BaseButton :busy="phase === 'starting'" :disabled="problem !== null" @click="requestDevices">
            {{ phase === 'starting' ? 'Waiting for you...' : deviceError || permissionBlocked ? 'Try again' : 'Allow camera and microphone' }}
          </BaseButton>
        </div>
      </StepCard>

      <!-- 4. check the devices -->
      <StepCard
        :index="4"
        :title="STEP_TITLES.devices"
        :state="stateOf(keys.indexOf('devices'))"
        :summary="micChecked ? 'Camera and microphone working.' : 'Camera working.'"
      >
        <div class="preview-wrap">
          <video ref="preview" class="preview" autoplay muted playsinline />
          <span class="live" :class="{ ok: cameraOk }"><Icon :name="cameraOk ? 'check' : 'alert'" size="0.9em" />
            {{ cameraOk ? 'Camera working' : 'No picture' }}</span>
        </div>
        <p v-if="!cameraOk" role="alert" class="error">The camera is not sending a picture.</p>

        <template v-if="micChecked">
          <p class="prompt">{{ MIC_PROMPT }}</p>
          <LevelMeter :level="level" />
          <p v-if="muted" role="alert" class="error">{{ MIC_MUTED_MESSAGE }}</p>
          <p v-if="micPassed" role="status" class="ok"><Icon name="check" size="1em" /> Microphone working.</p>
          <template v-if="mic.result === 'failed'">
            <p role="alert" class="error">{{ muted ? MIC_MUTED_MESSAGE : MIC_QUIET_MESSAGE }}</p>
            <BaseButton variant="secondary" @click="mic = INITIAL_MIC_CHECK">Try the microphone again</BaseButton>
          </template>
        </template>
        <p v-else class="muted">{{ MIC_CHECK_OFF_NOTE }}</p>

        <div class="actions gap-top">
          <BaseButton variant="ghost" @click="back">Back</BaseButton>
          <BaseButton :disabled="!devicesReady" @click="next">Continue</BaseButton>
        </div>
      </StepCard>

      <!-- 5. full screen -->
      <StepCard
        v-if="needsFullscreen"
        :index="5"
        :title="STEP_TITLES.fullscreen"
        :state="stateOf(keys.indexOf('fullscreen'))"
        summary="Full screen is on."
      >
        <p>{{ FULLSCREEN_LEAD }}</p>
        <Banner v-if="!fullscreen.supported" tone="bad" role="alert"><p>{{ FULLSCREEN_UNSUPPORTED }}</p></Banner>
        <Banner v-else-if="fullscreen.active.value" tone="good" role="status">
          <p>Full screen is on. {{ FULLSCREEN_EXIT_HINT }}</p>
        </Banner>
        <Banner v-if="fullscreenFailed && !fullscreen.active.value" tone="bad" role="alert">
          <p>Your browser did not switch to full screen. Press the button again.</p>
        </Banner>
        <div class="actions">
          <BaseButton variant="ghost" @click="back">Back</BaseButton>
          <BaseButton
            v-if="!fullscreen.active.value"
            :disabled="!fullscreen.supported"
            @click="goFullscreen"
          >
            <Icon name="fullscreen" size="1.1em" /> Go full screen
          </BaseButton>
          <BaseButton v-else @click="next">Continue</BaseButton>
        </div>
      </StepCard>

      <!-- 6. ready -->
      <StepCard
        :index="keys.length"
        :title="STEP_TITLES.ready"
        :state="stateOf(keys.indexOf('ready'))"
      >
        <div class="ready">
          <SuccessMark />
          <p>{{ READY_LEAD }}</p>
        </div>
        <ul class="summary-list">
          <li><Icon name="bell-off" size="1.05em" /> Notifications are off</li>
          <li><Icon name="camera" size="1.05em" /> Camera working</li>
          <li>
            <Icon name="mic" size="1.05em" />
            {{ micChecked ? 'Microphone working' : 'Microphone not tested in this run' }}
          </li>
          <li v-if="needsFullscreen"><Icon name="fullscreen" size="1.05em" /> Full screen on</li>
        </ul>
        <div class="actions">
          <BaseButton variant="ghost" @click="back">Back</BaseButton>
          <BaseButton size="lg" :busy="busy" @click="proceed">
            {{ busy ? 'Checking...' : 'Continue to the test' }}
          </BaseButton>
        </div>
        <Banner v-if="error" tone="bad" role="alert"><p>{{ error }}</p></Banner>
      </StepCard>
    </ol>
  </main>
</template>

<style scoped>
.progress {
  display: grid;
  gap: 0.4rem;
  margin: 1.25rem 0 1rem;
}

.steps {
  padding: 1.35rem 1.4rem 0.4rem;
  list-style: none;
}

.points {
  padding-left: 1.2rem;
  margin: 0 0 1rem;
}

.points li {
  margin-bottom: 0.45rem;
}

.help {
  padding-left: 1.2rem;
  margin: 0.5rem 0 0;
}

.status-line {
  margin: 0 0 0.9rem;
}

.pill {
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
  padding: 0.25rem 0.75rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--muted);
  background: var(--chip);
  border-radius: 999px;
  transition:
    color 200ms var(--ease-out),
    background-color 200ms var(--ease-out);
}

.pill.granted {
  color: var(--ok);
  background: var(--ok-tint);
}

.pill.denied {
  color: var(--danger);
  background: var(--danger-tint);
}

.pill.asking {
  color: var(--accent);
  background: var(--accent-tint);
}

.preview-wrap {
  position: relative;
  width: 100%;
  max-width: 22rem;
  margin-bottom: 0.75rem;
}

.preview {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: #000;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transform: scaleX(-1); /* a mirror, which is what people expect from their own camera */
}

.live {
  position: absolute;
  left: 0.6rem;
  bottom: 0.6rem;
  display: inline-flex;
  gap: 0.35rem;
  align-items: center;
  padding: 0.15rem 0.6rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: #fff;
  background: rgb(0 0 0 / 60%);
  border-radius: 999px;
}

.live.ok {
  color: #bff0d1;
}

.prompt {
  margin-bottom: 0.5rem;
  font-weight: 600;
}

.gap-top {
  margin-top: 1rem;
}

.ready {
  display: flex;
  gap: 0.9rem;
  align-items: center;
}

.ready p {
  margin: 0;
  font-weight: 600;
}

.summary-list {
  display: grid;
  gap: 0.5rem;
  padding: 0;
  margin: 1rem 0 1.1rem;
  list-style: none;
}

.summary-list li {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  color: var(--muted);
}

.summary-list :deep(.icon) {
  color: var(--ok);
}
</style>
