<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import Icon from '../components/Icon.vue'
import { api, pathForError } from '../lib/api'
import type { BeginResponse } from '../lib/api'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import { INTEGRITY_CHECKBOX, INTEGRITY_POINTS, INTEGRITY_TITLE } from './copy'

const router = useRouter()
const sessionId = getSessionId()
const agreed = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  if (!sessionId) void router.replace(CANDIDATE_PATH)
})

async function begin() {
  if (!sessionId) return
  busy.value = true
  error.value = null
  try {
    // The server starts the timer now, not when the page was opened.
    await api<BeginResponse>(`/api/session/${sessionId}/begin`, {
      method: 'POST',
      body: { accepted: true },
    })
    await router.replace('/test')
  } catch (e) {
    const route = pathForError(e)
    if (route && route !== '/integrity') await router.replace(route)
    else error.value = 'Something went wrong. Please try again.'
    busy.value = false
  }
}
</script>

<template>
  <main class="page">
    <BrandMark />
    <h1>{{ INTEGRITY_TITLE }}</h1>

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

    <p class="muted">Your time starts as soon as you press the button below.</p>
    <BaseButton size="lg" :disabled="!agreed" :busy="busy" @click="begin">
      {{ busy ? 'Starting...' : 'I agree, start the test' }}
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
