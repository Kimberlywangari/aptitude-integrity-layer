// A small stand-in for scripts/import_question_summary.py (D9): same columns, same checks, same
// report fields, so the admin screen can be exercised before the real importer exists.

import type { ImportReport, RejectedRow } from '../../src/lib/adminTypes'

export const REQUIRED_COLUMNS = [
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

export function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (c === '"') quoted = false
      else field += c
    } else if (c === '"') quoted = true
    else if (c === ',') {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      field = ''
      if (row.some((v) => v.trim() !== '')) rows.push(row)
      row = []
    } else field += c
  }
  row.push(field)
  if (row.some((v) => v.trim() !== '')) rows.push(row)
  return rows
}

export interface ImportedRow {
  question_id: string
  section: string
}

export type ImportOutcome =
  | { ok: true; report: ImportReport; imported: ImportedRow[] }
  | { ok: false; missing: string[] }

export function runImport(filename: string, csv: string, hasBank: boolean): ImportOutcome {
  const rows = parseCsv(csv)
  const header = (rows[0] ?? []).map((h) => h.trim().toLowerCase())
  const missing = REQUIRED_COLUMNS.filter((c) => !header.includes(c))
  if (missing.length) return { ok: false, missing }

  const col = (row: string[], name: string) => (row[header.indexOf(name)] ?? '').trim()
  const seen = new Set<string>()
  const rejected: RejectedRow[] = []
  const imported: ImportedRow[] = []
  let derived = 0

  rows.slice(1).forEach((row, i) => {
    const rowNumber = i + 2 // 1-based, counting the header
    const id = col(row, 'question_id')
    const reject = (reason: string) => rejected.push({ row: rowNumber, question_id: id || null, reason })

    if (!id) return reject('question_id is empty')
    if (seen.has(id)) return reject('duplicate question_id')
    seen.add(id)
    if (!/^[A-D]$/i.test(col(row, 'correct_option'))) return reject('correct_option must be A to D')

    const nums = ['n_candidates', 'pct_correct', 'median_s', 'p25_s', 'p75_s'].map((c) =>
      Number(col(row, c)),
    )
    if (nums.some((n) => !Number.isFinite(n) || n < 0)) return reject('a number is missing or negative')
    const [, pct, median, p25, p75] = nums
    if (pct > 100) return reject('pct_correct above 100')
    if (!(p25 <= median && median <= p75)) return reject('p25 <= median <= p75 does not hold')

    if (!col(row, 'difficulty_tag')) derived++
    imported.push({ question_id: id, section: col(row, 'section') || 'unknown' })
  })

  const warnings: string[] = []
  if (!header.includes('text') && !hasBank) {
    warnings.push(
      'The summary has no question text and no question-bank export was given. Join it with the ' +
        'bank export before a sitting; questions without text cannot be shown to candidates.',
    )
  }
  if (derived > 0) {
    warnings.push(`${derived} rows had no difficulty tag; it was derived from pct_correct.`)
  }

  return {
    ok: true,
    imported,
    report: {
      filename,
      rows: Math.max(0, rows.length - 1),
      imported: imported.length,
      rejected,
      warnings,
      difficulty_derived: derived,
    },
  }
}
