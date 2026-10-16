import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import type { Component } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import App from '../../src/App.vue'
import { createAppRouter } from '../../src/router'
import { track } from './mounted'

const text = (value: string) => defineComponent({ render: () => h('p', value) })

/**
 * Mounts a page inside a router that knows only the routes given. A string stands in for another
 * page (it renders that text), so a test can see where a redirect ended up.
 */
export async function mountPage(path: string, routes: Record<string, Component | string>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: Object.entries(routes).map(([routePath, page]) => ({
      path: routePath,
      component: typeof page === 'string' ? text(page) : page,
    })),
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(
    defineComponent({ render: () => h(RouterView) }),
    { global: { plugins: [router] }, attachTo: document.body },
  )
  track(wrapper)
  return { wrapper, router }
}

/** Mounts the whole app (the real routes and guards) at an address. */
export async function renderApp(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body })
  track(wrapper)
  return { wrapper, router }
}

/** Lets pending promises and the DOM catch up, optionally moving fake timers forward first. */
export async function settle(advance?: (ms: number) => Promise<unknown>, ms = 0) {
  if (advance) await advance(ms)
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

/** Waits (in real time) until something true shows up, for screens that fetch before they draw. */
export async function until(check: () => boolean, timeoutMs = 3000): Promise<void> {
  const started = Date.now()
  while (!check()) {
    if (Date.now() - started > timeoutMs) throw new Error('timed out waiting for the page')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
}
