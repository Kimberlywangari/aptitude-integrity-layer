<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import type { QueueResponse } from '../lib/reviewTypes'
import QueueTable from './QueueTable.vue'

const route = useRoute()
const router = useRouter()
const sitting = computed(() => (typeof route.query.sitting === 'string' ? route.query.sitting : null))

const { data, isPending, isError, refetch } = useQuery({
  queryKey: ['queue', sitting],
  queryFn: () =>
    api<QueueResponse>(
      `/api/review/queue${sitting.value ? `?sitting=${encodeURIComponent(sitting.value)}` : ''}`,
    ),
})

const main = computed(() => data.value?.items.filter((i) => !i.logging_only) ?? [])
const lowLane = computed(() => data.value?.items.filter((i) => i.logging_only) ?? [])

const changeSitting = (event: Event) =>
  router.push({ query: { sitting: (event.target as HTMLSelectElement).value } })
</script>

<template>
  <p v-if="isPending" role="status">Loading the queue...</p>
  <Banner v-else-if="isError" tone="bad" role="alert">
    <p>
      Could not load the queue.
      <BaseButton variant="secondary" @click="refetch()">Try again</BaseButton>
    </p>
  </Banner>
  <template v-else-if="data">
    <h1>Review queue</h1>
    <label class="field" for="sitting">Sitting</label>
    <select id="sitting" :value="data.sitting_id" @change="changeSitting">
      <option v-for="s in data.sittings" :key="s.id" :value="s.id">{{ s.name }}</option>
    </select>

    <p class="muted">
      Every flagged candidate is here. The order is a suggestion to help you start; nobody is set
      aside, and the AI never decides anything.
    </p>

    <p v-if="data.items.length === 0">
      No flagged candidates in this sitting yet. Flags appear once the sitting is closed and the
      jobs have run.
    </p>

    <template v-else>
      <QueueTable :items="main" />

      <section v-if="lowLane.length > 0" aria-labelledby="low-lane">
        <h2 id="low-lane">Logging problems only (low priority)</h2>
        <p class="muted">
          A gap in the page's heartbeat that a dropped connection or reload does not explain. These
          sit at the bottom, but a person should still look at them.
        </p>
        <QueueTable :items="lowLane" />
      </section>
    </template>
  </template>
</template>
