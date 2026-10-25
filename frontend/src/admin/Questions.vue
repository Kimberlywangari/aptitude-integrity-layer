<script setup lang="ts">
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import { api, ApiError } from '../lib/api'
import type {
  ImportReport,
  ImportRequest,
  QuestionBankSummary,
  QuestionListResponse,
  QuestionRow,
  RetireResponse,
} from '../lib/adminTypes'

const REQUIRED = [
  'question_id',
  'section',
  'correct_option',
  'difficulty_tag',
  'n_candidates',
  'pct_correct',
  'median_s',
  'p25_s',
  'p75_s',
]
const PAGE = 100
const DIFFICULTY_PILL = { easy: 'low', medium: 'moderate', hard: 'high' } as const

function importMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'sitting_open') {
      return 'A sitting is open. Close it before changing the question bank.'
    }
    if (error.code === 'missing_columns') {
      const columns = Array.isArray(error.body.columns) ? error.body.columns.join(', ') : ''
      const which = error.body.file === 'bank' ? 'The question-bank file' : 'The file'
      return `${which} is missing these columns: ${columns}.`
    }
    if (error.code === 'too_many_rows') {
      return `That file has too many rows. Split it into files of at most ${String(error.body.max ?? 5000)}.`
    }
  }
  return 'Could not import the file.'
}

const queryClient = useQueryClient()
const summaryFile = ref<File | null>(null)
const bankFile = ref<File | null>(null)
const report = ref<ImportReport | null>(null)
const confirmRetire = ref(false)
const retired = ref<RetireResponse | null>(null)
const section = ref('')

const { data: bank, isPending: bankPending } = useQuery({
  queryKey: ['admin', 'bank'],
  queryFn: () => api<QuestionBankSummary>('/api/admin/questions/summary'),
})

// The table loads a page at a time: a bank can hold thousands of questions.
const list = useInfiniteQuery({
  queryKey: ['admin', 'questions', section],
  initialPageParam: 0,
  queryFn: ({ pageParam }) =>
    api<QuestionListResponse>(
      `/api/admin/questions?limit=${PAGE}&offset=${pageParam}${
        section.value ? `&section=${encodeURIComponent(section.value)}` : ''
      }`,
    ),
  getNextPageParam: (last, pages) => {
    const loaded = pages.reduce((n, page) => n + page.questions.length, 0)
    return loaded < last.total ? loaded : undefined
  },
})
const rows = computed<QuestionRow[]>(() => list.data.value?.pages.flatMap((p) => p.questions) ?? [])
const matching = computed(() => list.data.value?.pages[0]?.total ?? 0)

const refresh = () =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: ['admin', 'bank'] }),
    queryClient.invalidateQueries({ queryKey: ['admin', 'questions'] }),
  ])

const {
  mutate: runImport,
  isPending: importing,
  isError: importFailed,
  error: importError,
} = useMutation({
  mutationFn: async () => {
    if (!summaryFile.value) throw new Error('no file')
    const body: ImportRequest = {
      filename: summaryFile.value.name,
      summary_csv: await summaryFile.value.text(),
      bank_csv: bankFile.value ? await bankFile.value.text() : null,
    }
    return api<ImportReport>('/api/admin/questions/import', { method: 'POST', body })
  },
  onSuccess: async (data) => {
    report.value = data
    await refresh()
  },
})

const {
  mutate: retire,
  isPending: retiring,
  isError: retireFailed,
  error: retireError,
} = useMutation({
  mutationFn: () =>
    api<RetireResponse>('/api/admin/questions/retire-synthetic', { method: 'POST', body: {} }),
  onSuccess: async (data) => {
    retired.value = data
    confirmRetire.value = false
    await refresh()
  },
})

const fileOf = (event: Event) => (event.target as HTMLInputElement).files?.[0] ?? null

function submit() {
  report.value = null
  runImport()
}
</script>

<template>
  <p v-if="bankPending" role="status">Loading the question bank...</p>
  <section v-if="bank" class="panel">
    <h2>What is in the bank</h2>
    <p>{{ bank.total }} questions: {{ bank.cytonn }} from Cytonn, {{ bank.synthetic }} practice.</p>
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Section</th>
            <th>Questions</th>
            <th>From Cytonn</th>
            <th>Practice</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in bank.by_section" :key="s.section">
            <td>{{ s.section }}</td>
            <td>{{ s.count }}</td>
            <td>{{ s.cytonn }}</td>
            <td>{{ s.synthetic }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="bank.synthetic > 0">
      <Banner tone="warn" role="status">
        <p>Practice questions are only used by practice sittings. Remove them before a real sitting.</p>
      </Banner>
      <div v-if="confirmRetire" class="actions">
        <BaseButton :busy="retiring" @click="retire()">Yes, remove {{ bank.synthetic }} practice questions</BaseButton>
        <BaseButton variant="secondary" @click="confirmRetire = false">Cancel</BaseButton>
      </div>
      <BaseButton v-else variant="secondary" @click="confirmRetire = true">
        Remove practice questions
      </BaseButton>
    </template>
    <p v-if="retired" role="status">
      Removed {{ retired.removed }} practice questions<template v-if="retired.kept > 0">; {{ retired.kept }} stay because an earlier test uses them</template>.
    </p>
    <Banner v-if="retireFailed" tone="bad" role="alert"><p>{{ importMessage(retireError) }}</p></Banner>
  </section>

  <section v-if="bank && bank.total > 0" class="panel" aria-labelledby="all-questions">
    <div class="row-between">
      <div>
        <h2 id="all-questions">Questions</h2>
        <p class="muted">
          "Answered correctly" fills in once Cytonn's past-sitting summary is loaded. Until then it
          says pending.
        </p>
      </div>
      <div>
        <label class="sr-only" for="section-filter">Section</label>
        <select id="section-filter" v-model="section">
          <option value="">All sections</option>
          <option v-for="s in bank.by_section" :key="s.section" :value="s.section">{{ s.section }}</option>
        </select>
      </div>
    </div>

    <p v-if="list.isPending.value" role="status">Loading the questions...</p>
    <Banner v-else-if="list.isError.value" tone="bad" role="alert">
      <p>Could not load the questions.</p>
    </Banner>
    <template v-else>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Section</th>
              <th>Difficulty</th>
              <th>Question</th>
              <th>From</th>
              <th>Answered correctly</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="q in rows" :key="q.id">
              <td class="mono">{{ q.id }}</td>
              <td>{{ q.section }}</td>
              <td>
                <span v-if="q.difficulty" class="pill" :class="DIFFICULTY_PILL[q.difficulty]">{{ q.difficulty }}</span>
                <span v-else class="muted">-</span>
              </td>
              <td class="preview" :title="q.preview">{{ q.preview }}</td>
              <td>
                <span class="pill plain" :class="{ ai: q.source === 'cytonn' }">{{ q.source === 'cytonn' ? 'Cytonn' : 'Practice' }}</span>
              </td>
              <td>
                <template v-if="q.pct_correct !== null">{{ Math.round(q.pct_correct) }}%<span class="muted"> of {{ q.n }}</span></template>
                <span v-else class="muted">Pending</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="muted">Showing {{ rows.length }} of {{ matching }}.</p>
      <BaseButton
        v-if="list.hasNextPage.value"
        variant="secondary"
        :busy="list.isFetchingNextPage.value"
        @click="list.fetchNextPage()"
      >
        Show more
      </BaseButton>
    </template>
  </section>

  <form class="panel" @submit.prevent="submit">
    <h2>Import Cytonn's question summary</h2>
    <p class="muted">
      A CSV with these columns: {{ REQUIRED.join(', ') }}. If it has no question text, add the
      question-bank export too and the two are joined on question_id.
    </p>
    <label class="field" for="summary">Question summary (required)</label>
    <input id="summary" type="file" accept=".csv,text/csv" @change="summaryFile = fileOf($event)" />
    <label class="field" for="bank">Question-bank export (optional)</label>
    <input id="bank" type="file" accept=".csv,text/csv" @change="bankFile = fileOf($event)" />
    <BaseButton type="submit" :disabled="!summaryFile" :busy="importing">
      {{ importing ? 'Importing...' : 'Import' }}
    </BaseButton>
    <Banner v-if="importFailed" tone="bad" role="alert"><p>{{ importMessage(importError) }}</p></Banner>
  </form>

  <section v-if="report" class="panel" aria-label="Import report">
    <h2>Import report</h2>
    <p role="status">
      {{ report.filename }}: {{ report.imported }} of {{ report.rows }} rows imported,
      {{ report.rejected.length }} rejected.
    </p>
    <Banner v-for="w in report.warnings" :key="w" tone="warn"><p>{{ w }}</p></Banner>
    <div v-if="report.rejected.length > 0" class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>Row</th>
            <th>Question</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in report.rejected" :key="`${r.row}-${r.reason}`">
            <td>{{ r.row }}</td>
            <td>{{ r.question_id ?? '' }}</td>
            <td>{{ r.reason }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
