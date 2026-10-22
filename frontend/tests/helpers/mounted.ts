import type { VueWrapper } from '@vue/test-utils'

// Kept free of app imports on purpose: tests/setup.ts loads this before a test file's vi.mock calls
// run, and anything the app imports from here would be loaded un-mocked.
const mounted: VueWrapper[] = []

export function track<T extends VueWrapper>(wrapper: T): T {
  mounted.push(wrapper)
  return wrapper
}

/** Unmounts every page a test mounted, so listeners and timers never leak into the next test. */
export function unmountAll(): void {
  while (mounted.length) mounted.pop()!.unmount()
}
