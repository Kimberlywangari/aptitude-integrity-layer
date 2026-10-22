<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { api, ApiError } from '../lib/api'
import type { LoginResponse } from '../lib/reviewTypes'
import { homeFor, LOGIN_PATH, safeNext } from '../lib/routes'
import { getStaff, saveStaff } from '../lib/staffSession'
import type { StaffRole } from '../lib/staffSession'
import { waitPhrase } from '../lib/wait'

type Area = StaffRole
type Problem =
  | { kind: 'credentials' }
  | { kind: 'wrong-area' }
  | { kind: 'too-many'; seconds: number }
  | { kind: 'other' }

const props = defineProps<{ area: Area }>()

const COPY: Record<Area, { title: string; lead: string; other: Area; otherLabel: string }> = {
  reviewer: {
    title: 'Reviewer sign in',
    lead: 'For people who review flagged candidates.',
    other: 'admin',
    otherLabel: 'Setting up a sitting? Admin sign in',
  },
  admin: {
    title: 'Admin sign in',
    lead: 'For people who set up sittings, questions and invitations.',
    other: 'reviewer',
    otherLabel: 'Reviewing candidates? Reviewer sign in',
  },
}

const router = useRouter()
const route = useRoute()
const next = safeNext(typeof route.query.next === 'string' ? route.query.next : null)
const copy = computed(() => COPY[props.area])
const email = ref('')
const password = ref('')
const busy = ref(false)
const problem = ref<Problem | null>(null)

// The reviewer card is open to admins too (they can see the review pages) and lands on the
// queue; the admin card is not open to reviewers, so a signed-in reviewer is sent to the queue.
const landing = (role: StaffRole) => (props.area === 'admin' ? homeFor(role) : '/review')

const existing = getStaff()
if (existing) void router.replace(next ?? landing(existing.role))

function describe(p: Problem): string {
  switch (p.kind) {
    case 'credentials':
      return 'The email or password is not right.'
    case 'wrong-area':
      return 'This account is a reviewer account, which cannot open the admin pages.'
    case 'too-many':
      return `Too many wrong attempts. Please wait ${waitPhrase(p.seconds)} and try again.`
    default:
      return 'Something went wrong. Please try again.'
  }
}

async function submit() {
  busy.value = true
  problem.value = null
  try {
    const session = await api<LoginResponse>('/api/review/login', {
      method: 'POST',
      body: { email: email.value.trim(), password: password.value },
    })
    if (props.area === 'admin' && session.role !== 'admin') {
      // Signed in, but not for this door: keep nothing, say so.
      problem.value = { kind: 'wrong-area' }
      busy.value = false
      return
    }
    saveStaff(session)
    await router.replace(next ?? landing(session.role))
  } catch (e) {
    if (e instanceof ApiError && e.code === 'invalid_credentials') {
      problem.value = { kind: 'credentials' }
    } else if (e instanceof ApiError && e.code === 'too_many_attempts') {
      const seconds = typeof e.body.retry_after_s === 'number' ? e.body.retry_after_s : 60
      problem.value = { kind: 'too-many', seconds }
    } else {
      problem.value = { kind: 'other' }
    }
    busy.value = false
  }
}
</script>

<template>
  <main class="page narrow">
    <p class="back"><RouterLink to="/">All sign-ins</RouterLink></p>
    <BrandMark />
    <h1>{{ copy.title }}</h1>
    <p class="lead">{{ copy.lead }}</p>

    <form class="card rise" @submit.prevent="submit">
      <label class="field" for="email">Email</label>
      <input id="email" v-model="email" type="email" autocomplete="username" autofocus />
      <label class="field" for="password">Password</label>
      <input id="password" v-model="password" type="password" autocomplete="current-password" />
      <BaseButton type="submit" size="lg" block :busy="busy" :disabled="!email.trim() || !password">
        {{ busy ? 'Signing in...' : 'Sign in' }}
      </BaseButton>
    </form>

    <Banner v-if="problem" tone="bad" role="alert">
      <p>
        {{ describe(problem) }}
        <template v-if="problem.kind === 'wrong-area'">
          <RouterLink :to="LOGIN_PATH.reviewer">Use the reviewer sign in</RouterLink>.
        </template>
      </p>
    </Banner>

    <p class="muted switch">
      <RouterLink :to="LOGIN_PATH[copy.other]">{{ copy.otherLabel }}</RouterLink>
    </p>
  </main>
</template>

<style scoped>
.back {
  margin: 0 0 1rem;
}

.switch {
  margin-top: 1.5rem;
}
</style>
