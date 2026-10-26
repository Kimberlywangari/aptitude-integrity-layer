<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, watch } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type { ProcessStatus } from '../lib/adminTypes'
import { formatDateTime } from '../lib/format'

// Prepares a closed sitting for the reviewers: the flags, the joined recordings, the quiet-stretch
// scan, the evidence packets and the order of the flagged candidates. It is the same run the command
// line makes (`process_sitting`), started from here and left to run on the server.
const props = defineProps<{ sittingId: number; closed: boolean }>()

const POLL_MS = 2000
const queryClient = useQueryClient()
const key = computed(() => ['admin', 'sittings', props.sittingId, 'process'])

const { data } = useQuery({
  queryKey: key,
  queryFn: () => api<ProcessStatus>(`/api/admin/sittings/${props.sittingId}/process`),
  refetchInterval: (query) => (query.state.data?.state === 'running' ? POLL_MS : false),
})

const { mutate: start, error: startError } = useMutation({
  mutationFn: () =>
    api<ProcessStatus>(`/api/admin/sittings/${props.sittingId}/process`, { method: 'POST' }),
  onSuccess: (status) => queryClient.setQueryData(key.value, status),
})

// Whatever the reviewers' screens held from before the run is out of date once it finishes.
watch(
  () => data.value?.state,
  (now, before) => {
    if (before !== 'running' || now !== 'done') return
    for (const name of ['queue', 'candidates', 'overview']) {
      void queryClient.invalidateQueries({ queryKey: [name] })
    }
  },
)

const running = computed(() => data.value?.state === 'running')
const hasRun = computed(() => !!data.value && (data.value.state !== 'idle' || !!data.value.last_ranked_at))
const how = computed(() => {
  const s = data.value
  if (!s || s.provider === 'rules') return 'The order comes from the rules alone; no AI is used.'
  const who = s.provider === 'claude' ? `Claude (${s.model})` : `The local model ${s.model}`
  return (
    `${who} ranks and explains the flagged candidates. Every answer is checked against the log, ` +
    'and a candidate whose answer fails the check keeps the order the rules gave.'
  )
})
const startMessage = computed(() => {
  const e = startError.value
  if (!e) return null
  return e instanceof ApiError && e.code === 'sitting_not_closed'
    ? 'Close the sitting first.'
    : 'Could not start it.'
})
</script>

<template>
  <section class="panel" aria-labelledby="process-heading">
    <h2 id="process-heading">Prepare for review</h2>
    <p class="muted">
      Works out the flags, joins the recordings, listens for long quiet stretches, builds the evidence
      for each flagged candidate and puts them in order for the reviewers. Run it once the sitting is
      closed and the recordings have finished arriving. Running it again is safe. {{ how }}
    </p>
    <p v-if="!closed" class="muted">
      Close the sitting first: the checks that compare candidates with each other need it closed.
    </p>

    <div class="actions">
      <BaseButton :busy="running" :disabled="!closed || running" @click="start()">
        {{ running ? 'Working...' : hasRun ? 'Process again' : 'Process sitting' }}
      </BaseButton>
    </div>
    <Banner v-if="startMessage" tone="bad" role="alert"><p>{{ startMessage }}</p></Banner>

    <p v-if="running" role="status">
      Working since {{ formatDateTime(data!.started_at) }}. This page updates by itself; with a local
      model it can take several minutes.
    </p>
    <Banner v-else-if="data?.state === 'done'" tone="good" role="status">
      <p>Finished {{ formatDateTime(data.finished_at) }}. The reviewers' queue is up to date.</p>
    </Banner>
    <Banner v-else-if="data?.state === 'failed'" tone="bad" role="alert">
      <p>{{ data.error }} What was finished is kept; you can run it again.</p>
    </Banner>
    <p v-else-if="data?.last_ranked_at" class="muted">
      Last prepared {{ formatDateTime(data.last_ranked_at) }}.
    </p>

    <div v-if="data && data.steps.length > 0" class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Step</th>
            <th>Seconds</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="step in data.steps" :key="step.label">
            <td class="nowrap">{{ step.label }}</td>
            <td class="nowrap">{{ step.seconds }}</td>
            <td>{{ step.note }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
