<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { ApiError } from '../lib/api'
import { resumeUpload } from '../lib/resume'
import { waitPhrase } from '../lib/wait'
import { HELP_CONTACT, RESUME_ERRORS, RESUME_LEAD, RESUME_TITLE, START_ERRORS, START_FALLBACK_ERROR } from './copy'

// For a candidate whose test is over but whose recording is not all with us: they closed the tab, or
// the connection gave out. The invitation code is swapped for an upload-only key that is good for
// 48 hours after the test, and the upload screen then sends what this computer still holds.
// Nothing here can start or change a test, and nothing can read a question.

const router = useRouter()
const route = useRoute()

const fromLink = typeof route.query.t === 'string' ? route.query.t : ''
const token = ref(fromLink)
const error = ref<string | null>(null)
const busy = ref(false)
const input = ref<HTMLInputElement | null>(null)

function messageFor(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'too_many_attempts') {
      const seconds = typeof e.body.retry_after_s === 'number' ? e.body.retry_after_s : 60
      return `Too many wrong codes. Please wait ${waitPhrase(seconds)} and try again.`
    }
    if (RESUME_ERRORS[e.code]) return RESUME_ERRORS[e.code]
    if (START_ERRORS[e.code]) return START_ERRORS[e.code]
  }
  return START_FALLBACK_ERROR
}

async function resume(invitation: string) {
  busy.value = true
  error.value = null
  try {
    await resumeUpload(invitation)
    await router.replace('/uploading')
  } catch (e) {
    error.value = messageFor(e)
    busy.value = false
  }
}

onMounted(() => {
  if (fromLink) void resume(fromLink)
  else input.value?.focus()
})

function onSubmit() {
  if (token.value.trim()) void resume(token.value)
}
</script>

<template>
  <main class="page narrow start">
    <BrandMark />
    <h1>{{ RESUME_TITLE }}</h1>
    <p class="lead">{{ RESUME_LEAD }}</p>

    <form class="card rise" @submit.prevent="onSubmit">
      <label class="field" for="invitation">Invitation code</label>
      <input
        id="invitation"
        ref="input"
        v-model="token"
        class="code"
        autocomplete="off"
        autocapitalize="characters"
        autocorrect="off"
        spellcheck="false"
        placeholder="XXXX-XXXX"
        :disabled="busy"
      />
      <BaseButton type="submit" size="lg" block :busy="busy" :disabled="!token.trim()">
        {{ busy ? 'Checking...' : 'Continue' }}
      </BaseButton>
    </form>

    <Banner v-if="error" tone="bad" role="alert">
      <p>{{ error }}</p>
      <p class="muted">{{ HELP_CONTACT }}</p>
    </Banner>
  </main>
</template>

<style scoped>
.code {
  margin-bottom: 1rem;
  font-family: var(--font-mono);
  font-size: max(16px, 1.35rem);
  letter-spacing: 0.12em;
  text-align: center;
  text-transform: uppercase;
}

.code::placeholder {
  color: var(--field-line);
  text-transform: none;
}
</style>
