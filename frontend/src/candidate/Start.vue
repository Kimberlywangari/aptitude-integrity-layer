<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { api, ApiError } from '../lib/api'
import type { SessionStatus, StartResponse } from '../lib/api'
import { formatOpensAt } from '../lib/format'
import { resumeUpload } from '../lib/resume'
import { saveSession } from '../lib/session'
import { canSignIn, MIN_PASSWORD_CHARS, signInBody } from '../lib/signIn'
import type { SignIn } from '../lib/signIn'
import { waitPhrase } from '../lib/wait'
import {
  FORGOT_PASSWORD,
  HELP_CONTACT,
  notOpenYet,
  PASSWORDS_DIFFER,
  START_ERRORS,
  START_FALLBACK_ERROR,
  START_LEAD,
  START_LEAD_CREATING,
} from './copy'
import SignInFields from './SignInFields.vue'

const router = useRouter()
const route = useRoute()

const fromLink = typeof route.query.t === 'string' ? route.query.t : ''
const token = ref(fromLink)
const email = ref('')
const password = ref('')
const repeat = ref('')
const creating = ref(false) // the code and email were right and no password exists yet: choose one
const error = ref<string | null>(null)
const busy = ref(false)
const fields = ref<InstanceType<typeof SignInFields> | null>(null)

function messageFor(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'too_many_attempts') {
      const seconds = typeof e.body.retry_after_s === 'number' ? e.body.retry_after_s : 60
      return `Too many wrong tries. Please wait ${waitPhrase(seconds)} and try again.`
    }
    if (e.code === 'sitting_not_open_yet' && typeof e.body.opens_at === 'string') {
      return notOpenYet(formatOpensAt(e.body.opens_at))
    }
    if (START_ERRORS[e.code]) return START_ERRORS[e.code]
  }
  return START_FALLBACK_ERROR
}

function routeFor(status: SessionStatus): string {
  if (status === 'in_progress') return '/test'
  if (status === 'finished') return '/done'
  return '/precheck' // permissions and device check first; it hands over to /integrity
}

function credentials(): SignIn {
  return creating.value
    ? { token: token.value, email: email.value, password: '', newPassword: password.value }
    : { token: token.value, email: email.value, password: password.value }
}

async function start() {
  error.value = null
  if (creating.value) {
    // checked here as well as on the server, so a typo does not cost a round trip
    if (password.value.length < MIN_PASSWORD_CHARS) {
      error.value = START_ERRORS.password_too_short
      return
    }
    if (password.value !== repeat.value) {
      error.value = PASSWORDS_DIFFER
      return
    }
  }
  const signIn = credentials()
  busy.value = true
  try {
    const body = await api<StartResponse>('/api/session/start', {
      method: 'POST',
      body: signInBody(signIn),
    })
    saveSession(body.session_id, body.access_token)
    await router.replace(routeFor(body.status))
  } catch (e) {
    if (e instanceof ApiError && e.code === 'password_needed') {
      // not a mistake: the code and email are right, and it is their first time
      creating.value = true
      password.value = ''
      repeat.value = ''
      busy.value = false
      return
    }
    // Once the sitting has closed, a code can no longer start anything. If the candidate already
    // took the test and part of the recording is still unsent, the same sign-in finishes the upload.
    if (e instanceof ApiError && e.code === 'no_open_sitting' && (await resumedUpload(signIn))) {
      return
    }
    error.value = messageFor(e)
    busy.value = false
  }
}

async function resumedUpload(signIn: SignIn): Promise<boolean> {
  try {
    await resumeUpload({ ...signIn, newPassword: undefined })
    await router.replace('/uploading')
    return true
  } catch {
    return false // nothing to resume: the message about the test not being open stands
  }
}

// An invitation link carries the code as ?t=..., so the candidate only has to type their email and
// password. The test never starts by itself: the sign-in is checked as a whole.
onMounted(() => {
  if (fromLink) fields.value?.focusEmail()
  else fields.value?.focusCode()
})

const ready = computed(() =>
  creating.value
    ? password.value !== '' && repeat.value !== ''
    : canSignIn({ token: token.value, email: email.value, password: password.value }),
)
</script>

<template>
  <main class="page narrow start">
    <BrandMark />
    <h1>Start your test</h1>
    <p class="lead">{{ creating ? START_LEAD_CREATING : START_LEAD }}</p>

    <form class="card rise" @submit.prevent="start()">
      <SignInFields
        ref="fields"
        v-model:token="token"
        v-model:email="email"
        v-model:password="password"
        v-model:repeat="repeat"
        :creating="creating"
        :busy="busy"
      />
      <BaseButton type="submit" size="lg" block :busy="busy" :disabled="!ready">
        {{ creating ? 'Create password and continue' : busy ? 'Starting...' : 'Continue' }}
      </BaseButton>
    </form>

    <Banner v-if="error" tone="bad" role="alert">
      <p>{{ error }}</p>
      <p class="muted">{{ HELP_CONTACT }}</p>
    </Banner>
    <p v-else-if="!creating" class="muted">{{ FORGOT_PASSWORD }}</p>
  </main>
</template>
