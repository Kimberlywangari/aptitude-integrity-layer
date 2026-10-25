// A question's text with its pictures put back where they belong.
//
// The server sends plain text in which each picture is marked `[[image 1]]`, `[[image 2]]`..., and
// the pictures' addresses in the same order. This cuts the text at the markers, so the page shows a
// paragraph, a picture, the next paragraph, exactly as the question was written. Nothing here is
// HTML: text stays text, and the only thing rendered as an element is an <img> the page builds.

export type Part =
  | { kind: 'text'; text: string }
  | { kind: 'image'; src: string; number: number }

const MARKER = /\[\[image (\d+)\]\]/g

export function partsOf(text: string, images: readonly string[] = []): Part[] {
  const parts: Part[] = []
  let from = 0
  for (const match of text.matchAll(MARKER)) {
    const before = text.slice(from, match.index).trim()
    if (before) parts.push({ kind: 'text', text: before })
    const number = Number(match[1])
    const src = images[number - 1]
    // a marker with no picture behind it is dropped, not shown as stray brackets
    if (src) parts.push({ kind: 'image', src, number })
    from = (match.index ?? 0) + match[0].length
  }
  const rest = text.slice(from).trim()
  if (rest) parts.push({ kind: 'text', text: rest })
  return parts.length > 0 ? parts : [{ kind: 'text', text }]
}
