<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { applyTheme, currentTheme, storedTheme, systemTheme } from '../lib/theme'
import type { Theme } from '../lib/theme'
import Icon from './Icon.vue'

// A small corner button, on every page. It follows the system setting until the person picks
// one, then keeps their choice.
const theme = ref<Theme>(currentTheme())
let query: MediaQueryList | null = null

function onSystemChange() {
  if (storedTheme()) return
  const next = systemTheme()
  applyTheme(next, false)
  theme.value = next
}

onMounted(() => {
  if (typeof window.matchMedia !== 'function') return
  query = window.matchMedia('(prefers-color-scheme: dark)')
  query.addEventListener('change', onSystemChange)
})

onBeforeUnmount(() => query?.removeEventListener('change', onSystemChange))

function toggle() {
  const next: Theme = theme.value === 'dark' ? 'light' : 'dark'
  applyTheme(next)
  theme.value = next
}
</script>

<template>
  <button type="button" class="theme-toggle" @click="toggle">
    <Icon :name="theme === 'dark' ? 'sun' : 'moon'" size="1.05em" />
    <span>{{ theme === 'dark' ? 'Light mode' : 'Dark mode' }}</span>
  </button>
</template>

<style scoped>
/* Fixed in the corner. .page keeps 5rem of bottom padding, so it never covers the last line. */
.theme-toggle {
  position: fixed;
  right: max(1rem, env(safe-area-inset-right));
  bottom: max(1rem, env(safe-area-inset-bottom));
  z-index: 30;
  display: inline-flex;
  gap: 0.45rem;
  align-items: center;
  min-height: 2.5rem;
  padding: 0.4rem 0.85rem;
  font: inherit;
  font-size: 0.88rem;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 999px;
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  touch-action: manipulation;
  user-select: none;
  -webkit-user-select: none;
  transition:
    transform 140ms var(--ease-out),
    border-color 140ms var(--ease-out),
    background-color 140ms var(--ease-out);
}

.theme-toggle:active {
  transform: scale(0.96);
}

@media (hover: hover) and (pointer: fine) {
  .theme-toggle:hover {
    background: var(--accent-tint);
    border-color: var(--accent);
  }
}

@media (prefers-reduced-motion: reduce) {
  .theme-toggle:active {
    transform: none;
  }
}
</style>
