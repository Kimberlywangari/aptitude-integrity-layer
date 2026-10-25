<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { ApiError } from '../lib/api'
import { resumeUpload } from '../lib/resume'
import { canSignIn, MIN_PASSWORD_CHARS } from '../lib/signIn'
import { waitPhrase } from '../lib/wait'
import {
  FORGOT_PASSWORD,
  HELP_CONTACT,
  PASSWORDS_DIFFER,
  RESUME_ERRORS,
  RESUME_LEAD,
  RESUME_TITLE,
  START_ERRORS,
  START_FALLBACK_ERROR,
} from './copy'
import SignInFields from './SignInFields.vue'

// For a candidate whose test is over but whose recording is not all with us: they closed the tab, or
// the connection gave out. The sign-in (the same as the start page's) is swapped for an upload-only
// key that is good for 48 hours after the test, and the upload screen then sends what this computer
// still holds. Nothing here can start or change a test, and nothing can read a question.

const router = useRouter()
const route = useRoute()

const fromLink = typeof route.query.t === 'string' ? route.query.t : ''
const token = ref(fromLink)
const email = ref('')
const password = ref('')
const repeat = ref('')
const creating = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)
const fields = ref<InstanceType<typeof SignInFields> | null>(null)

function messageFor(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'too_many_attempts') {
      const seconds = typeof e.body.retry_after_s === 'number' ? e.body.retry_after_s : 60
      return `Too many wrong tries. Please wait ${waitPhrase(seconds)} and try again.`
    }
    if (RESUME_ERRORS[e.code]) return RESUME_ERRORS[e.code]
    if (START_ERRORS[e.code]) return START_ERRORS[e.code]
  }
  return START_FALLBACK_ERROR
}

async function resume() {
  error.value = null
  if (creating.value) {
    if (password.value.length < MIN_PASSWORD_CHARS) {
      error.value = START_ERRORS.password_too_short
      return
    }
    if (password.value !== repeat.value) {
      error.value = PASSWORDS_DIFFER
      return
    }
  }
  busy.value = true
  try {
    await resumeUpload({
      token: token.value,
      email: email.value,
      password: creating.value ? '' : password.value,
      newPassword: creating.value ? password.value : undefined,
    })
    await router.replace('/uploading')
  } catch (e) {
    if (e instanceof ApiError && e.code === 'password_needed') {
      creating.value = true
      password.value = ''
      repeat.value = ''
      busy.value = false
      return
    }
    error.value = messageFor(e)
    busy.value = false
  }
}

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
    <h1>{{ RESUME_TITLE }}</h1>
    <p class="lead">{{ RESUME_LEAD }}</p>

    <form class="card rise" @submit.prevent="resume()">
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
        {{ creating ? 'Create password and continue' : busy ? 'Checking...' : 'Continue' }}
      </BaseButton>
    </form>

    <Banner v-if="error" tone="bad" role="alert">
      <p>{{ error }}</p>
      <p class="muted">{{ HELP_CONTACT }}</p>
    </Banner>
    <p v-else-if="!creating" class="muted">{{ FORGOT_PASSWORD }}</p>
  </main>
</template>
