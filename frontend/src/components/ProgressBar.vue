<script setup lang="ts">
import { computed } from 'vue'

// A thin progress bar. Scaled with transform, so growing it never relayouts the page.
const props = withDefaults(
  defineProps<{
    value: number
    max: number
    label: string
    tone?: 'accent' | 'ok' | 'warn' | 'danger'
  }>(),
  { tone: 'accent' },
)

const fraction = computed(() => (props.max > 0 ? Math.min(Math.max(props.value / props.max, 0), 1) : 0))
</script>

<template>
  <div
    class="bar"
    role="progressbar"
    :aria-label="label"
    aria-valuemin="0"
    :aria-valuemax="max"
    :aria-valuenow="value"
  >
    <div class="fill" :class="tone" :style="{ transform: `scaleX(${fraction})` }" />
  </div>
</template>

<style scoped>
.bar {
  width: 100%;
  height: 0.5rem;
  overflow: hidden;
  background: var(--chip);
  border-radius: 999px;
}

.fill {
  width: 100%;
  height: 100%;
  background: var(--accent);
  border-radius: 999px;
  transform-origin: left center;
  transition:
    transform 400ms var(--ease-out),
    background-color 300ms var(--ease-out);
}

.fill.ok {
  background: var(--ok);
}

.fill.warn {
  background: var(--warn-line);
}

.fill.danger {
  background: var(--danger);
}

@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: background-color 300ms ease;
  }
}
</style>
