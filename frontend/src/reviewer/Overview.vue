<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api } from '../lib/api'
import { humaniseKind } from '../lib/format'
import type { HealthCheck, OverviewResponse } from '../lib/reviewTypes'
import BandChip from './BandChip.vue'
import { FLAG_LABELS } from './copy'

const route = useRoute()
const router = useRouter()
const sitting = computed(() => (typeof route.query.sitting === 'string' ? route.query.sitting : null))

// Without a sitting this is the same query as the one the rail uses, so they share one request.
const { data, isPending, isError, refetch } = useQuery({
  queryKey: ['overview', sitting],
  queryFn: () =>
    api<OverviewResponse>(
      `/api/review/overview${sitting.value ? `?sitting=${encodeURIComponent(sitting.value)}` : ''}`,
    ),
  staleTime: 15_000,
})

const CHECK_WORDS: Record<HealthCheck['state'], string> = {
  ok: 'OK',
  warn: 'Needs a look',
  off: 'Off',
  note: 'To look at',
}

const kindLabel = (kind: string) => FLAG_LABELS[kind] ?? humaniseKind(kind)
const widest = computed(() => Math.max(1, ...(data.value?.flags_by_kind.map((k) => k.count) ?? [])))
const flaggedCount = computed(() => data.value?.tiles.flagged ?? 0)
const percentReviewed = computed(() =>
  flaggedCount.value ? Math.round(((data.value?.tiles.reviewed ?? 0) / flaggedCount.value) * 100) : 0,
)

const changeSitting = (event: Event) =>
  router.push({ query: { sitting: (event.target as HTMLSelectElement).value } })
</script>

<template>
  <p v-if="isPending" role="status">Loading the overview...</p>
  <Banner v-else-if="isError" tone="bad" role="alert">
    <p>
      Could not load the overview.
      <BaseButton variant="secondary" @click="refetch()">Try again</BaseButton>
    </p>
  </Banner>

  <template v-else-if="data">
    <header class="page-head">
      <div>
        <h1>Overview</h1>
        <p>Where the sitting stands, and which flagged candidates still need a person to look.</p>
      </div>
      <div v-if="data.sittings.length > 0">
        <label class="sr-only" for="sitting">Sitting</label>
        <select id="sitting" :value="data.sitting_id" @change="changeSitting">
          <option v-for="s in data.sittings" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>
    </header>

    <p v-if="data.sittings.length === 0">
      There is no sitting yet. An admin creates one under Admin, then invites the candidates.
    </p>

    <template v-else>
      <Banner v-if="data.sitting_status === 'open'" tone="info" role="status">
        <p>
          This sitting is still open. Flags and the review queue appear once it is closed and the
          jobs have run.
        </p>
      </Banner>

      <div class="tiles">
        <div class="tile">
          <h2>Candidates</h2>
          <div class="tile-n">{{ data.tiles.sat }}</div>
          <p>Sat this sitting</p>
        </div>
        <div class="tile">
          <h2>Flagged</h2>
          <div class="tile-n">{{ data.tiles.flagged }}</div>
          <p>Each reaches a reviewer</p>
        </div>
        <div class="tile">
          <h2>Reviewed</h2>
          <div class="tile-n">
            {{ data.tiles.reviewed }} <small>of {{ data.tiles.flagged }}</small>
          </div>
          <p>Counted when a written decision is saved</p>
        </div>
        <div class="tile">
          <h2>Videos uploaded</h2>
          <div class="tile-n">
            {{ data.tiles.videos_uploaded }} <small>of {{ data.tiles.videos_expected }}</small>
          </div>
          <p>{{ data.tiles.videos_decided_not_deleted }} decided, on the clock for deletion</p>
        </div>
      </div>

      <div class="cols-2">
        <section class="panel" aria-labelledby="kinds">
          <h2 id="kinds">Flags by kind</h2>
          <p class="muted">
            Counts across the whole sitting. A lone focus loss counts for little on its own.
          </p>
          <p v-if="data.flags_by_kind.length === 0" class="muted">No flags in this sitting.</p>
          <ul v-else class="bars">
            <li v-for="k in data.flags_by_kind" :key="k.kind" class="bar">
              <span>{{ kindLabel(k.kind) }}</span>
              <span class="track" aria-hidden="true">
                <span :style="{ width: `${Math.round((k.count / widest) * 100)}%` }" />
              </span>
              <b>{{ k.count }}</b>
            </li>
          </ul>
        </section>

        <div class="stack">
          <section class="panel" aria-labelledby="progress">
            <h2 id="progress">Review progress</h2>
            <div
              class="track"
              role="progressbar"
              aria-label="Flagged candidates decided"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="percentReviewed"
            >
              <span :style="{ width: `${percentReviewed}%` }" />
            </div>
            <p class="muted">
              {{ data.tiles.reviewed }} of {{ data.tiles.flagged }} flagged candidates decided
            </p>
          </section>

          <section class="panel" aria-labelledby="checks">
            <h2 id="checks">System checks</h2>
            <ul class="checks">
              <li v-for="check in data.checks" :key="check.key">
                <span>{{ check.label }}</span>
                <span class="pill" :class="check.state === 'off' ? 'plain' : check.state">{{
                  CHECK_WORDS[check.state]
                }}</span>
                <small>{{ check.detail }}</small>
              </li>
            </ul>
          </section>
        </div>
      </div>

      <section class="panel" aria-labelledby="next">
        <h2 id="next">Needs a person next</h2>
        <p v-if="data.next_up.length === 0" class="muted">
          {{
            data.tiles.flagged === 0
              ? 'No one is flagged in this sitting yet.'
              : 'Everyone flagged has been decided.'
          }}
        </p>
        <RouterLink
          v-for="n in data.next_up"
          :key="n.candidate_id"
          :to="`/review/candidates/${n.candidate_id}`"
          class="next-row"
        >
          <strong class="mono">{{ n.candidate_id }}</strong>
          <span class="grow"
            >{{ n.flag_count }} flag{{ n.flag_count === 1 ? '' : 's' }}, {{ kindLabel(n.first_kind).toLowerCase() }}
            first</span
          >
          <BandChip :band="n.band" long />
        </RouterLink>
        <p v-if="data.pending > data.next_up.length" class="muted">
          <RouterLink to="/review">{{ data.pending }} waiting in the queue</RouterLink>
        </p>
      </section>
    </template>
  </template>
</template>
