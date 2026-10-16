<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import BrandMark from '../components/BrandMark.vue'
import { api, pathForError } from '../lib/api'
import type { ComplaintCategory, ComplaintRequest } from '../lib/api'
import { CANDIDATE_PATH } from '../lib/routes'
import { getSessionId } from '../lib/session'
import {
  COMPLAINT_CATEGORIES,
  COMPLAINT_NOTE_LABEL,
  COMPLAINT_THANKS,
  COMPLAINT_TITLE,
} from './copy'

const MAX_CHARS = 1000

const router = useRouter()
const sessionId = getSessionId()
const category = ref<ComplaintCategory | null>(null)
const text = ref('')
const busy = ref(false)
const sent = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  if (!sessionId) void router.replace(CANDIDATE_PATH)
})

async function submit() {
  if (!category.value || !text.value.trim()) return
  busy.value = true
  error.value = null
  const body: ComplaintRequest = { category: category.value, text: text.value.trim() }
  try {
    await api('/api/complaints', { method: 'POST', body })
    sent.value = true
  } catch (e) {
    const route = pathForError(e)
    if (route && route !== '/complaint') await router.replace(route)
    else error.value = 'Could not send that. Please try again.'
  } finally {
    busy.value = false
  }
}

const back = () => router.back()
</script>

<template>
  <main class="page narrow">
    <BrandMark />
    <h1>{{ COMPLAINT_TITLE }}</h1>

    <template v-if="sent">
      <Banner tone="good" role="status"><p>{{ COMPLAINT_THANKS }}</p></Banner>
      <BaseButton variant="secondary" @click="back">Back</BaseButton>
    </template>

    <form v-else class="card" @submit.prevent="submit">
      <fieldset>
        <legend class="sr-only">What kind of problem</legend>
        <label v-for="c in COMPLAINT_CATEGORIES" :key="c.value" class="option">
          <input v-model="category" type="radio" name="category" :value="c.value" />
          <span class="mark" aria-hidden="true" />
          <span>{{ c.label }}</span>
        </label>
      </fieldset>

      <label class="field" for="text">{{ COMPLAINT_NOTE_LABEL }}</label>
      <textarea id="text" v-model="text" rows="5" :maxlength="MAX_CHARS" />
      <p class="muted">{{ text.length }}/{{ MAX_CHARS }}</p>

      <div class="actions">
        <BaseButton type="submit" :busy="busy" :disabled="!category || !text.trim()">
          {{ busy ? 'Sending...' : 'Send' }}
        </BaseButton>
        <BaseButton variant="secondary" @click="back">Back</BaseButton>
      </div>
      <Banner v-if="error" tone="bad" role="alert"><p>{{ error }}</p></Banner>
    </form>
  </main>
</template>
