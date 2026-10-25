// Reading the words out of a file an admin chose: a PDF, a Word, Excel or PowerPoint file, an
// OpenDocument file, RTF, HTML or plain text. The server does the reading and decides what the
// file is from its bytes, so every kind goes the same way and there is one set of problems to word.
// Staff screens only: nothing here is in the candidate's bundle.

import { api, ApiError } from './api'

export interface ReadDocument {
  text: string
  kind: string
}

/** The text of `file`; with `want: 'table'`, its first table as CSV rows. Throws an ApiError. */
export async function readDocument(file: File, want: 'text' | 'table' = 'text'): Promise<ReadDocument> {
  return api<ReadDocument>(`/api/admin/extract-text?want=${want}`, { method: 'POST', bytes: file })
}

const PROBLEMS: Record<string, string> = {
  empty_file: 'That file is empty.',
  file_too_large: 'That file is too big. The limit is 5 MB.',
  legacy_office_format:
    'That is an old Word, Excel or PowerPoint file (.doc, .xls, .ppt), which cannot be read. Open it, ' +
    'save it as .docx, .xlsx or .pptx, and choose it again.',
  scanned_pdf:
    'That PDF is pictures of pages, so there are no words in it to read, and nothing here reads ' +
    'pictures. Use the original file, or save the PDF with its text.',
  password_protected: 'That file is password protected. Take the password off and choose it again.',
  no_table_found:
    'No table was found in that file. This needs rows and columns: a spreadsheet, a table in a Word ' +
    'file, or a CSV.',
  no_text_found: 'There are no words in that file.',
  too_much_text: 'That file holds far more text than this needs.',
  unsupported_type:
    'That kind of file cannot be read. Use a PDF, Word, Excel, PowerPoint or OpenDocument file, ' +
    'RTF, HTML, or plain text.',
  unreadable_file: 'That file could not be read. It may be damaged; try saving it again.',
}

/** What to tell the person when a file could not be read, or null if it was not the file's fault. */
export function documentProblem(error: unknown): string | null {
  return error instanceof ApiError ? (PROBLEMS[error.code] ?? null) : null
}
