import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { clearSession, getStage, saveSession } from '../src/lib/session'
import { createAppRouter } from '../src/router'

const newRouter = () => createAppRouter(createMemoryHistory())

describe('no way back into the test once it is over', () => {
  beforeEach(() => {
    saveSession('s1', 'tok')
  })

  afterEach(() => {
    clearSession()
  })

  it('lets a candidate who has not finished move through the test screens', async () => {
    const router = newRouter()
    for (const path of ['/precheck', '/integrity', '/test']) {
      await router.push(path)
      expect(router.currentRoute.value.path).toBe(path)
    }
    expect(getStage()).toBeNull()
  })

  it('sends anyone who asks for a test screen after the finish page back to it', async () => {
    const router = newRouter()
    await router.push('/done')
    for (const path of ['/test', '/integrity', '/precheck']) {
      await router.push(path)
      expect(router.currentRoute.value.path).toBe('/done')
    }
  })

  it('sends them to the upload page once the closing answers have been sent', async () => {
    const router = newRouter()
    await router.push('/done')
    await router.replace('/uploading')
    for (const path of ['/test', '/integrity', '/precheck', '/done']) {
      await router.push(path)
      expect(router.currentRoute.value.path).toBe('/uploading')
    }
  })

  it('holds against the browser Back button, however far back it goes', async () => {
    const router = newRouter()
    await router.push('/test')
    await router.push('/done')
    await router.replace('/uploading')

    router.back() // the test screen is the entry behind
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/uploading')
  })

  it('still lets the candidate reach the complaint page and come back', async () => {
    const router = newRouter()
    await router.push('/done')
    await router.push('/complaint')
    expect(router.currentRoute.value.path).toBe('/complaint')
  })

  it('starts afresh for a different candidate on the same tab', async () => {
    const router = newRouter()
    await router.push('/done')
    expect(getStage()).toBe('finished')

    saveSession('s2', 'tok2') // a new invitation code was entered
    expect(getStage()).toBeNull()
    await router.push('/test')
    expect(router.currentRoute.value.path).toBe('/test')
  })
})
