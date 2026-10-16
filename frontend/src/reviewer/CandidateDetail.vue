<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import { formatDateTime, formatElapsed, humaniseKind, ordinal } from '../lib/format'
import type {
  CandidateDetail as Detail,
  InnocentSignal,
  VideoSeek,
  VsSitting,
} from '../lib/reviewTypes'
import {
  AI_LABEL,
  CONTEXT_ONLY,
  DETAIL_LABELS,
  FLAG_LABELS,
  INNOCENT_LABELS,
  OUTCOME_LABELS,
  RETENTION_NOTE,
  RULES_LABEL,
  orderBasis,
} from './copy'
import DecisionForm from './DecisionForm.vue'
import VideoPlayer from './VideoPlayer.vue'
import type { JumpTarget } from './VideoPlayer.vue'

const props = defineProps<{ id: string }>()

const queryClient = useQueryClient()
const target = ref<JumpTarget | null>(null)
let nonce = 0

const { data, isPending, isError, error } = useQuery({
  queryKey: ['candidate', computed(() => props.id)],
  queryFn: () => api<Detail>(`/api/review/candidates/${encodeURIComponent(props.id)}`),
})

const { mutate: toggleShortlist, isPending: shortlisting } = useMutation({
  mutationFn: () =>
    api<{ shortlisted: boolean }>(`/api/review/candidates/${encodeURIComponent(props.id)}/shortlist`, {
      method: 'POST',
    }),
  onSuccess: async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['candidate', props.id] }),
      queryClient.invalidateQueries({ queryKey: ['queue'] }),
    ])
  },
})

function jump(seek: VideoSeek | null, label: string, flagId?: string) {
  nonce += 1
  target.value = seek
    ? { kind: 'seek', segment: seek.segment, seekS: seek.seek_s, label, nonce }
    : { kind: 'none', label, nonce }
  // Every jump is a video view the audit log must hold. It never blocks the jump.
  void api(`/api/review/candidates/${encodeURIComponent(props.id)}/video-view`, {
    method: 'POST',
    body: { flag_id: flagId ?? null },
  }).catch(() => undefined)
}

function detailText(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => {
      const shown = Array.isArray(value)
        ? value.join(', ')
        : typeof value === 'boolean'
          ? value
            ? 'yes'
            : 'no'
          : String(value)
      return `${DETAIL_LABELS[key] ?? humaniseKind(key)}: ${shown}`
    })
    .join(' · ')
}

function cohortLines(vs: VsSitting): string[] {
  if (vs.cohort_skipped) {
    return ['Not compared: too few finished candidates in this sitting for a fair comparison.']
  }
  const line = (label: string, value: number | undefined) =>
    value === undefined ? null : `${label}: ${ordinal(value)} percentile of the sitting`
  return [
    line('Pace', vs.pace_percentile),
    line('Answer-time spread', vs.spread_percentile),
    line('Score', vs.score_percentile),
  ].filter((l): l is string => l !== null)
}

function signalText(signal: InnocentSignal): string {
  const label = INNOCENT_LABELS[signal.kind] ?? humaniseKind(signal.kind)
  const parts: string[] = []
  if (signal.elapsed_s !== undefined) parts.push(`at ${formatElapsed(signal.elapsed_s)}`)
  if (signal.duration_s !== undefined) parts.push(`${signal.duration_s} s`)
  if (signal.note) parts.push(`"${signal.note}"`)
  return parts.length ? `${label}: ${parts.join(', ')}` : label
}

const flagLabel = (kind: string) => FLAG_LABELS[kind] ?? humaniseKind(kind)
const notFound = computed(() => error.value instanceof ApiError && error.value.code === 'candidate_not_found')
const latestDecision = computed(() => data.value?.decisions[data.value.decisions.length - 1])
const aiShown = computed(() => data.value?.explanation.source === 'ai')
</script>

<template>
  <p v-if="isPending" role="status">Loading the candidate...</p>

  <template v-else-if="isError">
    <Banner tone="bad" role="alert">
      <p>{{ notFound ? 'That candidate is not in the review queue.' : 'Could not load the candidate.' }}</p>
    </Banner>
    <p><RouterLink to="/review">Back to the queue</RouterLink></p>
  </template>

  <template v-else-if="data">
    <header class="detail-header">
      <h1>Candidate {{ data.candidate_id }}</h1>
      <span class="badge">Rank {{ data.rank }}</span>
      <span class="badge" :class="{ ai: aiShown }">
        {{ orderBasis(data.explanation.status, data.explanation.strength) }}
      </span>
      <span v-if="latestDecision" class="badge">Decided: {{ OUTCOME_LABELS[latestDecision.outcome] }}</span>
      <BaseButton variant="secondary" :busy="shortlisting" @click="toggleShortlist()">
        {{ data.shortlisted ? 'Remove from shortlist' : 'Add to shortlist' }}
      </BaseButton>
    </header>

    <div class="detail-grid">
      <div>
        <section class="panel">
          <h2>Summary</h2>
          <p class="muted">{{ aiShown ? AI_LABEL : RULES_LABEL }}</p>
          <p>{{ data.explanation.text }}</p>
          <p v-if="data.explanation.flags_support_each_other" class="muted">
            Do the flags support each other: {{ data.explanation.flags_support_each_other }}.
          </p>
        </section>

        <section class="panel">
          <h2>Flags</h2>
          <p v-if="data.flags.length === 0">No flags.</p>
          <ul v-else class="list">
            <li v-for="flag in data.flags" :key="flag.id">
              <div>
                <strong>{{ flagLabel(flag.kind) }}</strong>
                at {{ formatElapsed(flag.elapsed_s) }}<template v-if="flag.question_number !== null">, question {{ flag.question_number }}</template>
              </div>
              <div class="muted">{{ detailText(flag.detail) }}</div>
              <BaseButton variant="secondary" @click="jump(flag.video_seek, `${flag.id} ${flagLabel(flag.kind)}`, flag.id)">
                Jump to video
              </BaseButton>
            </li>
          </ul>
          <details>
            <summary>How the rule score of {{ data.rule_score }} adds up</summary>
            <ul>
              <li v-for="line in data.rule_breakdown" :key="line.label">{{ line.label }}: {{ line.points }}</li>
            </ul>
          </details>
        </section>

        <section class="panel">
          <h2>Compared with the sitting</h2>
          <ul>
            <li v-for="line in cohortLines(data.vs_sitting)" :key="line">{{ line }}</li>
          </ul>
          <p v-if="data.history_source === 'synthetic'" class="muted">
            The per-question history behind the "far faster than past candidates" flag is synthetic
            sample data, not Cytonn's.
          </p>
        </section>

        <section class="panel">
          <h2>Context</h2>
          <p class="muted">{{ CONTEXT_ONLY }}</p>
          <ul>
            <li>Score: {{ data.score }} correct</li>
            <li>Pace: {{ data.pace_s_per_q }} s per question</li>
          </ul>
        </section>

        <section class="panel">
          <h2>Things that may explain what you see</h2>
          <p v-if="data.innocent_signals.length === 0">None recorded.</p>
          <ul v-else>
            <li v-for="signal in data.innocent_signals" :key="signal.id">{{ signalText(signal) }}</li>
          </ul>
          <p v-if="data.self_report">
            Candidate's own report:
            {{
              data.self_report.had_technical_issues
                ? `technical problems${data.self_report.note ? `: "${data.self_report.note}"` : ''}`
                : 'no technical problems'
            }}
          </p>
        </section>

        <section class="panel">
          <h2>Muted or silent microphone</h2>
          <p class="muted">{{ CONTEXT_ONLY }}</p>
          <p v-if="data.mic_silence.length === 0">None of a minute or longer.</p>
          <ul v-else class="list">
            <li v-for="m in data.mic_silence" :key="m.id">
              <div>
                {{ formatElapsed(m.start_s) }} to {{ formatElapsed(m.end_s) }} ({{ m.duration_s }} s),
                seen by {{ m.layers.join(' and ') }}<template v-if="m.layers.includes('browser')"> (the candidate saw the warning)</template>
              </div>
              <BaseButton variant="secondary" @click="jump(m.video_seek, `Microphone ${m.id}`)">
                Jump to video
              </BaseButton>
            </li>
          </ul>
        </section>

        <section class="panel">
          <h2>Complaints</h2>
          <p v-if="data.complaints.length === 0">None filed.</p>
          <ul v-else>
            <li v-for="c in data.complaints" :key="c.id">
              {{ c.category }} ({{ c.status }}, {{ formatDateTime(c.created_at) }}): {{ c.text }}
            </li>
          </ul>
        </section>

        <section class="panel">
          <h2>Earlier decisions</h2>
          <p v-if="data.decisions.length === 0">None yet.</p>
          <ul v-else>
            <li v-for="p in data.decisions" :key="p.decided_at">
              {{ OUTCOME_LABELS[p.outcome] }} by {{ p.reviewer }}, {{ formatDateTime(p.decided_at) }}: {{ p.reason }}
            </li>
          </ul>
          <p class="muted">
            {{ RETENTION_NOTE }}
            <template v-if="data.video_purge_on">
              Video is due for deletion on {{ formatDateTime(data.video_purge_on) }}.
            </template>
          </p>
        </section>
      </div>

      <aside class="detail-side">
        <VideoPlayer :segments="data.segments" :target="target" :deleted-at="data.video_deleted_at" />
        <DecisionForm :session-id="data.session_id" :candidate-id="data.candidate_id" />
      </aside>
    </div>
  </template>
</template>
