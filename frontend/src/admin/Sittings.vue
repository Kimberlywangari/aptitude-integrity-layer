<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type {
  AdminSitting,
  AiSample,
  AiStatus,
  CloseSittingResponse,
  CreateSittingRequest,
  QuestionBankSummary,
  RetryPapersResponse,
} from '../lib/adminTypes'
import SetupSteps from './SetupSteps.vue'
import { createMessage } from './sittingErrors'
import { paperOf, stateOf, totalOf, windowOf } from './sittingText'

const DEFAULT_PER_SECTION = 4
const DEFAULT_CYTONN_PER_SECTION = 2
// Every question gets 1.75 minutes (105 s); the server sets the sitting's time from the count.
const MINUTES_PER_QUESTION = 1.75
// A written paper takes a while on a local model, so the first form is a small one.
const DEFAULT_AI_PER_CATEGORY: Record<string, number> = { numerical: 2, verbal: 2, logical: 2 }

function toIso(local: string): string | null {
  if (!local) return null
  const date = new Date(local)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

const queryClient = useQueryClient()
const router = useRouter()
const name = ref('')
const opensAt = ref('')
const closesAt = ref('')
type Mode = 'cytonn' | 'ai' | 'practice'
const mode = ref<Mode>('practice')
const modeChosen = ref(false) // until someone picks, the form follows what the bank holds
// One set of counts per mode, so switching back and forth does not lose what was typed.
const wantedBy = ref<Record<Mode, Record<string, number>>>({ cytonn: {}, practice: {}, ai: {} })
const wanted = computed(() => wantedBy.value[mode.value])
const wantedAi = computed(() => wantedBy.value.ai)
const sampleCategory = ref('numerical')
const sampleDifficulty = ref<'easy' | 'medium' | 'hard'>('medium')
const needsForce = ref<{ id: number; unfinished: number } | null>(null)
const closeError = ref<string | null>(null)

const { data: sittings, isPending: sittingsPending, isError: sittingsError } = useQuery({
  queryKey: ['admin', 'sittings'],
  queryFn: () => api<{ sittings: AdminSitting[] }>('/api/admin/sittings'),
})
const { data: bank } = useQuery({
  queryKey: ['admin', 'bank'],
  queryFn: () => api<QuestionBankSummary>('/api/admin/questions/summary'),
})

const { data: ai } = useQuery({
  queryKey: ['admin', 'ai-status'],
  queryFn: () => api<AiStatus>('/api/admin/ai-questions/status'),
  enabled: computed(() => mode.value === 'ai'),
})
const aiCategories = computed(() => ai.value?.categories ?? [])
const maxPerCategory = computed(() => ai.value?.max_per_category ?? 30)
watch(
  aiCategories,
  (found) => {
    if (found.length === 0 || Object.keys(wantedBy.value.ai).length > 0) return
    wantedBy.value.ai = Object.fromEntries(
      found.map((c) => [c.key, DEFAULT_AI_PER_CATEGORY[c.key] ?? 0]),
    )
  },
  { immediate: true },
)

// The sections this mode can draw from, with how many questions each holds. Cytonn's sitting sees
// only Cytonn's questions and a practice sitting only the made-up ones: they never mix.
const sections = computed(() =>
  (bank.value?.by_section ?? [])
    .map((s) => ({ section: s.section, count: mode.value === 'cytonn' ? s.cytonn : s.synthetic }))
    .filter((s) => s.count > 0),
)
// Until someone picks a mode, Cytonn's questions are the default once they are loaded.
watch(
  bank,
  (found) => {
    if (!modeChosen.value && found) mode.value = found.cytonn > 0 || found.synthetic === 0 ? 'cytonn' : 'practice'
  },
  { immediate: true },
)
// A few of each section to start with, so the form is usable straight away. Filled once per
// mode: later changes to the bank must not overwrite what someone has typed.
watch(
  [sections, mode],
  ([found, current]) => {
    if (current === 'ai' || found.length === 0 || Object.keys(wantedBy.value[current]).length > 0) return
    const each = current === 'cytonn' ? DEFAULT_CYTONN_PER_SECTION : DEFAULT_PER_SECTION
    wantedBy.value[current] = Object.fromEntries(found.map((s) => [s.section, Math.min(each, s.count)]))
  },
  { immediate: true },
)

const inBank = (section: string) => sections.value.find((s) => s.section === section)?.count ?? 0
const idOf = (section: string) => section.replace(/\s+/g, '-')
const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, Number.isFinite(value) ? Math.round(value) : low))

function setWanted(section: string, value: number) {
  wantedBy.value[mode.value] = {
    ...wantedBy.value[mode.value],
    [section]: clamp(value, 0, inBank(section)),
  }
}

function setWantedAi(category: string, value: number) {
  wantedBy.value.ai = { ...wantedBy.value.ai, [category]: clamp(value, 0, maxPerCategory.value) }
}

const activeWanted = computed(() => wantedBy.value[mode.value])
const total = computed(() => Object.values(activeWanted.value).reduce((n, v) => n + v, 0))
const usedSections = computed(() => Object.values(activeWanted.value).filter((v) => v > 0).length)
const minutes = computed(() => Math.ceil(total.value * MINUTES_PER_QUESTION))

const {
  mutate: createSitting,
  isPending: creating,
  isError: createFailed,
  error: createError,
} = useMutation({
  mutationFn: (body: CreateSittingRequest) =>
    api<AdminSitting>('/api/admin/sittings', { method: 'POST', body }),
  onSuccess: async () => {
    name.value = ''
    await queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] })
  },
})

const {
  mutate: trySample,
  data: sample,
  isPending: sampling,
  isError: sampleFailed,
  error: sampleError,
  reset: clearSample,
} = useMutation({
  mutationFn: () =>
    api<AiSample>('/api/admin/ai-questions/sample', {
      method: 'POST',
      body: { category: sampleCategory.value, difficulty: sampleDifficulty.value },
    }),
})

const { mutate: restartPapers, isPending: restarting } = useMutation({
  mutationFn: (id: number) =>
    api<RetryPapersResponse>(`/api/admin/sittings/${id}/retry-papers`, { method: 'POST' }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] }),
})

const sampleMessage = computed(() => {
  const e = sampleError.value
  if (!sampleFailed.value) return null
  if (e instanceof ApiError && typeof e.body.detail === 'string') return e.body.detail
  return 'The writer could not write a question.'
})

const { mutate: closeSitting, isPending: closing } = useMutation({
  mutationFn: (vars: { id: number; force: boolean }) =>
    api<CloseSittingResponse>(`/api/admin/sittings/${vars.id}/close`, {
      method: 'POST',
      body: { force: vars.force },
    }),
  onSuccess: async () => {
    needsForce.value = null
    closeError.value = null
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin', 'sittings'] }),
      queryClient.invalidateQueries({ queryKey: ['overview'] }),
      // closing works out the sitting's flags, so what the reviewer lists has changed
      queryClient.invalidateQueries({ queryKey: ['queue'] }),
      queryClient.invalidateQueries({ queryKey: ['candidates'] }),
    ])
  },
  onError: (error, vars) => {
    if (error instanceof ApiError && error.code === 'sessions_unfinished') {
      needsForce.value = { id: vars.id, unfinished: Number(error.body.unfinished ?? 0) }
      closeError.value = null
    } else {
      closeError.value = 'Could not close the sitting.'
    }
  },
})

const createMessageText = computed(() => createMessage(createError.value))
const letters = 'ABCDEFGH'

// A sitting's row opens its page. Clicks on the buttons and links inside it do their own thing.
function openSitting(event: MouseEvent, id: number) {
  if ((event.target as HTMLElement).closest('a, button, input, select, textarea, label')) return
  void router.push(`/admin/sittings/${id}`)
}

function submit() {
  createSitting({
    name: name.value.trim(),
    opens_at: toIso(opensAt.value),
    closes_at: toIso(closesAt.value),
    per_section: Object.fromEntries(Object.entries(activeWanted.value).filter(([, n]) => n > 0)),
    question_mode: mode.value,
  })
}
</script>

<template>
  <SetupSteps v-if="bank && sittings" :bank="bank" :sittings="sittings.sittings" />

  <Banner v-if="bank && bank.synthetic > 0" tone="warn" role="status">
    <p>
      {{ bank.synthetic }} practice questions are still in the question bank. Only practice
      sittings use them. <RouterLink to="/admin/questions">Remove them</RouterLink> once you do not need
      those.
    </p>
  </Banner>

  <section id="new-sitting" class="panel">
    <h2>New sitting</h2>
    <p class="muted">
      Each candidate gets a different paper with the numbers below, one timer, and no going back.
    </p>
    <form @submit.prevent="submit">
      <label class="field" for="name">Name</label>
      <input id="name" v-model="name" />
      <div class="field-row">
        <div>
          <label class="field" for="opens">Opens (optional)</label>
          <input id="opens" v-model="opensAt" type="datetime-local" />
        </div>
        <div>
          <label class="field" for="closes">Closes (optional)</label>
          <input id="closes" v-model="closesAt" type="datetime-local" />
        </div>
      </div>
      <p class="muted">
        Leave both empty and the sitting is open from the moment you create it until you close it. If you
        set an opening time, candidates who use their code before then are told when to come back.
      </p>

      <fieldset class="mode">
        <legend>Where the questions come from</legend>
        <label class="choice">
          <input v-model="mode" type="radio" name="mode" value="cytonn" @change="modeChosen = true" />
          <span>
            <strong>Cytonn's questions</strong>
            <span class="muted">
              Cytonn's own aptitude questions, in their seven sections. Each candidate gets a
              different random draw.
            </span>
          </span>
        </label>
        <label class="choice">
          <input v-model="mode" type="radio" name="mode" value="ai" @change="modeChosen = true" />
          <span>
            <strong>Written by AI for each candidate</strong>
            <span class="muted">
              New questions are written for every candidate when they open their link, so no two
              papers match.
            </span>
          </span>
        </label>
        <label v-if="bank && bank.synthetic > 0" class="choice">
          <input v-model="mode" type="radio" name="mode" value="practice" @change="modeChosen = true" />
          <span>
            <strong>Practice questions</strong>
            <span class="muted">
              The made-up bank, for trying the system out. These are not Cytonn's questions.
            </span>
          </span>
        </label>
      </fieldset>

      <template v-if="mode === 'ai'">
        <Banner v-if="ai && !ai.available" tone="warn" role="status">
          <p>{{ ai.detail }} An AI sitting cannot be created until the writer is reachable.</p>
        </Banner>
        <p v-else-if="ai" class="muted" role="status">
          Written by {{ ai.model }} ({{ ai.provider }}). Every question is checked a second time,
          without its answer, before a candidate can see it.
          <template v-if="ai.provider === 'ollama'">
            A slow computer writes about one question a minute, so try a small paper first. A model
            running on this computer can fail the checks on logic puzzles; the candidate is then
            offered to ask again. Claude writes far more reliably.
          </template>
        </p>
        <fieldset>
          <legend>Questions of each kind</legend>
          <ul class="section-rows">
            <li v-for="c in aiCategories" :key="c.key">
              <span class="name">
                <span>{{ c.label }}</span>
                <span class="muted block">{{ c.brief }}</span>
              </span>
              <span class="stepper">
                <button
                  type="button"
                  :aria-label="`Fewer ${c.label} questions`"
                  :disabled="(wantedAi[c.key] ?? 0) <= 0"
                  @click="setWantedAi(c.key, (wantedAi[c.key] ?? 0) - 1)"
                >
                  −
                </button>
                <input
                  :id="`ai-${c.key.replace(/\s+/g, '-')}`"
                  type="number"
                  min="0"
                  :max="maxPerCategory"
                  :aria-label="`${c.label} questions`"
                  :value="wantedAi[c.key] ?? 0"
                  @change="setWantedAi(c.key, Number(($event.target as HTMLInputElement).value))"
                />
                <button
                  type="button"
                  :aria-label="`More ${c.label} questions`"
                  :disabled="(wantedAi[c.key] ?? 0) >= maxPerCategory"
                  @click="setWantedAi(c.key, (wantedAi[c.key] ?? 0) + 1)"
                >
                  +
                </button>
              </span>
            </li>
          </ul>
        </fieldset>

      </template>

      <fieldset v-else>
        <legend>Questions from each section</legend>
        <Banner v-if="mode === 'cytonn' && sections.length === 0" tone="warn" role="status">
          <p>
            Cytonn's questions are not loaded yet. From a terminal in the backend folder run
            <code>python -m scripts.jobs fetch_cytonn_bank</code> (it needs the API key in .env), then
            reload this page.
          </p>
        </Banner>
        <p v-else-if="sections.length === 0" class="muted">The question bank is empty.</p>
        <ul v-else class="section-rows">
          <li v-for="s in sections" :key="s.section">
            <span class="name">
              <span class="cap">{{ s.section }}</span>
              <span class="muted">
                ({{ s.count }} {{ mode === 'cytonn' ? "from Cytonn" : 'in the practice bank' }})
              </span>
            </span>
            <span class="stepper">
              <button
                type="button"
                :aria-label="`Fewer ${s.section} questions`"
                :disabled="(wanted[s.section] ?? 0) <= 0"
                @click="setWanted(s.section, (wanted[s.section] ?? 0) - 1)"
              >
                −
              </button>
              <input
                :id="`per-${idOf(s.section)}`"
                type="number"
                min="0"
                :max="s.count"
                :aria-label="`${s.section} questions`"
                :value="wanted[s.section] ?? 0"
                @change="setWanted(s.section, Number(($event.target as HTMLInputElement).value))"
              />
              <button
                type="button"
                :aria-label="`More ${s.section} questions`"
                :disabled="(wanted[s.section] ?? 0) >= s.count"
                @click="setWanted(s.section, (wanted[s.section] ?? 0) + 1)"
              >
                +
              </button>
            </span>
          </li>
        </ul>
      </fieldset>

      <p id="paper-summary" class="muted" role="status">
        {{ total }} question{{ total === 1 ? '' : 's' }} from {{ usedSections }}
        section{{ usedSections === 1 ? '' : 's' }}. Each question gets 1 minute 45 seconds, so the test takes
        {{ minutes }} minutes.
      </p>
      <BaseButton type="submit" :busy="creating" :disabled="!name.trim() || total < 1">
        {{ creating ? 'Creating...' : 'Create sitting' }}
      </BaseButton>
    </form>
    <div v-if="mode === 'ai'" class="sample">
      <h3>Try the writer</h3>
      <p class="muted">
        Writes one real question the way a candidate's paper would, checks it, and shows it with
        its answer. Nothing is saved.
      </p>
      <div class="field-row">
        <div>
          <label class="field" for="sample-category">Kind</label>
          <select id="sample-category" v-model="sampleCategory">
            <option v-for="c in aiCategories" :key="c.key" :value="c.key">{{ c.label }}</option>
          </select>
        </div>
        <div>
          <label class="field" for="sample-difficulty">Level</label>
          <select id="sample-difficulty" v-model="sampleDifficulty">
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
        </div>
      </div>
      <BaseButton
        variant="secondary"
        :busy="sampling"
        :disabled="!ai?.available"
        @click="clearSample(); trySample()"
      >
        {{ sampling ? 'Writing and checking...' : 'Write one question' }}
      </BaseButton>
      <p v-if="sampling" class="muted" role="status">
        Writing, then checking it a second time. On a slow computer this takes a few minutes.
      </p>
      <Banner v-if="sampleMessage" tone="bad" role="alert"><p>{{ sampleMessage }}</p></Banner>
      <article v-if="sample" class="sample-card" aria-label="The question that was written">
        <p class="sample-text">{{ sample.text }}</p>
        <ol class="sample-options">
          <li v-for="(option, index) in sample.options" :key="index" :class="{ right: index === sample.correct_index }">
            <span class="letter">{{ letters[index] }}</span>
            <span>{{ option }}</span>
            <span v-if="index === sample.correct_index" class="muted"> (marked correct)</span>
          </li>
        </ol>
        <p class="muted">Working: {{ sample.explanation }}</p>
        <p class="muted">
          {{ sample.difficulty }} · written by {{ sample.written_by }} in {{ sample.seconds }} s, {{ sample.rounds }}
          round{{ sample.rounds === 1 ? '' : 's' }}
          <template v-if="sample.rejected.length"> · thrown away on the way: {{ sample.rejected.join('; ') }}</template>
        </p>
      </article>
    </div>
    <Banner v-if="createFailed" tone="bad" role="alert"><p>{{ createMessageText }}</p></Banner>
  </section>

  <p v-if="sittingsPending" role="status">Loading sittings...</p>
  <Banner v-if="sittingsError" tone="bad" role="alert"><p>Could not load the sittings.</p></Banner>
  <p v-if="sittings && sittings.sittings.length > 0" class="muted">
    Click a sitting to see who was invited and who has done the test.
  </p>
  <div v-if="sittings" class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Window</th>
          <th>Limit</th>
          <th>Paper</th>
          <th>Progress</th>
          <th>Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in sittings.sittings" :key="s.id" class="clickable" @click="openSitting($event, s.id)">
          <td><RouterLink :to="`/admin/sittings/${s.id}`">{{ s.name }}</RouterLink></td>
          <td>{{ windowOf(s) }}</td>
          <td class="nowrap">{{ Math.round(s.duration_s / 60) }} min</td>
          <td class="paper">
            {{ s.question_count }} questions<br /><span class="muted">{{ paperOf(s) }}</span>
          </td>
          <td>
            {{ s.counts.finished }} of {{ totalOf(s) }} finished<template v-if="s.counts.in_progress > 0">, {{ s.counts.in_progress }} sitting now</template>
            <template v-if="s.counts.papers_pending > 0"><br /><span class="muted">{{ s.counts.papers_pending }} still having questions written</span></template>
            <template v-if="s.counts.papers_failed > 0">
              <br /><span class="bad-text">{{ s.counts.papers_failed }} could not have questions written</span>
              <BaseButton variant="secondary" :disabled="restarting" @click="restartPapers(s.id)">
                Write them again
              </BaseButton>
            </template>
          </td>
          <td>
            <span class="pill" :class="stateOf(s).pill" :title="stateOf(s).title">{{ stateOf(s).label }}</span>
          </td>
          <td>
            <template v-if="s.status === 'open'">
              <template v-if="needsForce?.id === s.id">
                <span class="muted">{{ needsForce.unfinished }} not finished. </span>
                <BaseButton :disabled="closing" @click="closeSitting({ id: s.id, force: true })">
                  Close anyway (logged)
                </BaseButton>
              </template>
              <BaseButton v-else variant="secondary" :disabled="closing" @click="closeSitting({ id: s.id, force: false })">
                Close sitting
              </BaseButton>
            </template>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <Banner v-if="closeError" tone="bad" role="alert"><p>{{ closeError }}</p></Banner>
  <p class="muted">
    Flags and packets are built after a sitting is closed. Cohort checks need at least 8 finished
    candidates.
  </p>
</template>
