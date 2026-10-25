import { describe, expect, it } from 'vitest'
import { partsOf } from '../src/lib/questionText'

const A = '/api/session/s/image/1?t=a'
const B = '/api/session/s/image/2?t=b'

describe('partsOf', () => {
  it('is one paragraph when there is nothing to put back', () => {
    expect(partsOf('What is 2 + 2?')).toEqual([{ kind: 'text', text: 'What is 2 + 2?' }])
    expect(partsOf('What is 2 + 2?', [A])).toEqual([{ kind: 'text', text: 'What is 2 + 2?' }])
  })

  it('cuts the text at each marker and puts the matching picture there', () => {
    expect(partsOf('Study this.\n\n[[image 1]]\n\nWhich is tallest?\n\n[[image 2]]', [A, B])).toEqual([
      { kind: 'text', text: 'Study this.' },
      { kind: 'image', src: A, number: 1 },
      { kind: 'text', text: 'Which is tallest?' },
      { kind: 'image', src: B, number: 2 },
    ])
  })

  it('is just the picture for a question that is nothing else', () => {
    expect(partsOf('[[image 1]]', [A])).toEqual([{ kind: 'image', src: A, number: 1 }])
  })

  it('drops a marker with no picture behind it, and keeps the words around it', () => {
    expect(partsOf('Before.\n\n[[image 2]]\n\nAfter.', [A])).toEqual([
      { kind: 'text', text: 'Before.' },
      { kind: 'text', text: 'After.' },
    ])
  })

  it('keeps the line breaks inside a paragraph, for the page to show', () => {
    const parts = partsOf('Line one\nLine two\n\n[[image 1]]', [A])
    expect(parts[0]).toEqual({ kind: 'text', text: 'Line one\nLine two' })
  })

  it('never turns text into markup: what looks like a tag stays text', () => {
    const [part] = partsOf('<img src=x onerror=alert(1)> [not a marker]')
    expect(part).toEqual({ kind: 'text', text: '<img src=x onerror=alert(1)> [not a marker]' })
  })

  it('does not fall over on a marker with a huge or missing number', () => {
    expect(partsOf('a [[image 99999999999999999999]] b', [A]).map((p) => p.kind)).toEqual([
      'text',
      'text',
    ])
    expect(partsOf('a [[image ]] b', [A])).toEqual([{ kind: 'text', text: 'a [[image ]] b' }])
  })
})
