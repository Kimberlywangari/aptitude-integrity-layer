<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { api, ApiError } from '../lib/api'
import type { SessionStatus, StartResponse } from '../lib/api'
import { normaliseInviteCode } from '../lib/inviteCode'
import { saveSession } from '../lib/session'
import { waitPhrase } from '../lib/wait'
import { HELP_CONTACT, START_ERRORS, START_FALLBACK_ERROR } from './copy'

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
    if (START_ERRORS[e.code]) return START_ERRORS[e.code]
  }
  return START_FALLBACK_ERROR
}

function routeFor(status: SessionStatus): string {
  if (status === 'in_progress') return '/test'
  if (status === 'finished') return '/done'
  return '/precheck' // permissions and device check first; it hands over to /integrity
}

async function start(invitation: string) {
  busy.value = true
  error.value = null
  try {
    const body = await api<StartResponse>('/api/session/start', {
      method: 'POST',
      // Case, dashes and spaces are forgiven (lib/inviteCode.ts).
      body: { token: normaliseInviteCode(invitation) },
    })
    saveSession(body.session_id, body.access_token)
    await router.replace(routeFor(body.status))
  } catch (e) {
    error.value = messageFor(e)
    busy.value = false
  }
}

// An invitation link carries the code as ?t=..., so the candidate does not have to type it.
onMounted(() => {
  if (fromLink) void start(fromLink)
  else input.value?.focus()
})

function onSubmit() {
  if (token.value.trim()) void start(token.value)
}
</script>

<template>
  <main class="page narrow start">
    <BrandMark />
    <h1>Enter your invitation code</h1>
    <p class="lead">You will find it in the message that invited you.</p>

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
        {{ busy ? 'Starting...' : 'Continue' }}
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
