import { describe, expect, it } from 'vitest'
import { invitesToCsv } from '../src/lib/csv'

describe('invitesToCsv()', () => {
  it('writes the same columns as the seed script', () => {
    const csv = invitesToCsv(
      [{ candidate_id: 'cand-021', code: 'ABCD-EFGH' }],
      'https://test.example/',
    )
    expect(csv.split('\r\n')).toEqual([
      'candidate_id,token,url',
      'cand-021,ABCD-EFGH,https://test.example/?t=ABCD-EFGH',
    ])
  })

  it('puts the name and email beside the code when the invitations were made for people', () => {
    const csv = invitesToCsv(
      [{ candidate_id: 'cand-021', code: 'ABCD-EFGH', name: 'Lovelace, Ada', email: 'ada@example.org' }],
      'https://test.example',
      'Pilot',
    )
    expect(csv.split('\r\n')).toEqual([
      'candidate_id,name,email,token,url,sitting',
      'cand-021,"Lovelace, Ada",ada@example.org,ABCD-EFGH,https://test.example/?t=ABCD-EFGH,Pilot',
    ])
  })

  it('quotes cells that need it', () => {
    const csv = invitesToCsv([{ candidate_id: 'a,b', code: 'X"Y' }], 'http://h')
    expect(csv).toContain('"a,b","X""Y"')
  })
})
