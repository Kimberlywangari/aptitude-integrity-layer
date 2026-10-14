import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import type {
  ImportReport,
  ImportRequest,
  QuestionBankSummary,
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

function importMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'sitting_open') {
      return 'A sitting is open. Close it before changing the question bank.'
    }
    if (error.code === 'missing_columns') {
      const columns = Array.isArray(error.body.columns) ? error.body.columns.join(', ') : ''
      return `The file is missing these columns: ${columns}.`
    }
  }
  return 'Could not import the file.'
}

export default function Questions() {
  const queryClient = useQueryClient()
  const [summaryFile, setSummaryFile] = useState<File | null>(null)
  const [bankFile, setBankFile] = useState<File | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const [confirmRetire, setConfirmRetire] = useState(false)
  const [retired, setRetired] = useState<RetireResponse | null>(null)

  const bank = useQuery({
    queryKey: ['admin', 'bank'],
    queryFn: () => api<QuestionBankSummary>('/api/admin/questions/summary'),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin', 'bank'] })

  const importer = useMutation({
    mutationFn: async () => {
      if (!summaryFile) throw new Error('no file')
      const body: ImportRequest = {
        filename: summaryFile.name,
        summary_csv: await summaryFile.text(),
        bank_csv: bankFile ? await bankFile.text() : null,
      }
      return api<ImportReport>('/api/admin/questions/import', { method: 'POST', body })
    },
    onSuccess: async (data) => {
      setReport(data)
      await refresh()
    },
  })

  const retire = useMutation({
    mutationFn: () =>
      api<RetireResponse>('/api/admin/questions/retire-synthetic', { method: 'POST', body: {} }),
    onSuccess: async (data) => {
      setRetired(data)
      setConfirmRetire(false)
      await refresh()
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    setReport(null)
    importer.mutate()
  }

  return (
    <>
      <h1>Question bank</h1>

      {bank.isPending && <p role="status">Loading the question bank...</p>}
      {bank.data && (
        <section className="panel">
          <h2>What is in the bank</h2>
          <p>
            {bank.data.total} questions: {bank.data.cytonn} from Cytonn, {bank.data.synthetic}{' '}
            placeholders.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Section</th>
                <th>Questions</th>
                <th>From Cytonn</th>
                <th>Placeholders</th>
              </tr>
            </thead>
            <tbody>
              {bank.data.by_section.map((s) => (
                <tr key={s.section}>
                  <td>{s.section}</td>
                  <td>{s.count}</td>
                  <td>{s.cytonn}</td>
                  <td>{s.synthetic}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {bank.data.synthetic > 0 && (
            <>
              <p role="status" className="banner">
                Placeholder questions are drawn into papers like any other. Remove them before a
                real sitting.
              </p>
              {confirmRetire ? (
                <div className="actions">
                  <button
                    type="button"
                    disabled={retire.isPending}
                    onClick={() => retire.mutate()}
                  >
                    Yes, remove {bank.data.synthetic} placeholders
                  </button>
                  <button type="button" className="secondary" onClick={() => setConfirmRetire(false)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button type="button" className="secondary" onClick={() => setConfirmRetire(true)}>
                  Remove placeholder questions
                </button>
              )}
            </>
          )}
          {retired && (
            <p role="status">
              Removed {retired.removed} placeholders
              {retired.kept > 0 && `; ${retired.kept} stay because an earlier test uses them`}.
            </p>
          )}
          {retire.isError && (
            <p role="alert" className="error">
              {importMessage(retire.error)}
            </p>
          )}
        </section>
      )}

      <form className="panel" onSubmit={submit}>
        <h2>Import Cytonn's question summary</h2>
        <p className="muted">
          A CSV with these columns: {REQUIRED.join(', ')}. If it has no question text, add the
          question-bank export too and the two are joined on question_id.
        </p>
        <label htmlFor="summary">Question summary (required)</label>
        <input
          id="summary"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setSummaryFile(e.target.files?.[0] ?? null)}
        />
        <label htmlFor="bank">Question-bank export (optional)</label>
        <input
          id="bank"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setBankFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" disabled={!summaryFile || importer.isPending}>
          {importer.isPending ? 'Importing...' : 'Import'}
        </button>
        {importer.isError && (
          <p role="alert" className="error">
            {importMessage(importer.error)}
          </p>
        )}
      </form>

      {report && (
        <section className="panel" aria-label="Import report">
          <h2>Import report</h2>
          <p role="status">
            {report.filename}: {report.imported} of {report.rows} rows imported,{' '}
            {report.rejected.length} rejected.
          </p>
          {report.warnings.map((w) => (
            <p key={w} className="banner">
              {w}
            </p>
          ))}
          {report.rejected.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Question</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {report.rejected.map((r) => (
                  <tr key={`${r.row}-${r.reason}`}>
                    <td>{r.row}</td>
                    <td>{r.question_id ?? ''}</td>
                    <td>{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  )
}
