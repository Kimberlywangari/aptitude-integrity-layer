<script setup lang="ts">
import { computed } from 'vue'

// The microphone level as a bar. The fill is scaled with transform (cheap to repaint ten times a
// second); its width never changes.
const props = withDefaults(defineProps<{ level: number; max?: number; label?: string }>(), {
  max: 0.1,
  label: 'Microphone level',
})

const clamped = computed(() => Math.min(Math.max(props.level, 0), props.max))
const fill = computed(() => clamped.value / props.max)
</script>

<template>
  <div
    class="meter"
    role="meter"
    :aria-label="label"
    aria-valuemin="0"
    :aria-valuemax="max"
    :aria-valuenow="clamped"
  >
    <div class="fill" :style="{ transform: `scaleX(${fill})` }" />
  </div>
</template>

<style scoped>
.meter {
  width: 100%;
  max-width: 22rem;
  height: 0.65rem;
  overflow: hidden;
  background: var(--chip);
  border-radius: 999px;
}

.fill {
  width: 100%;
  height: 100%;
  background: var(--ok);
  border-radius: 999px;
  transform-origin: left center;
  transition: transform 90ms linear;
}

@media (prefers-reduced-motion: reduce) {
  .fill {
    transition: none;
  }
}
</style>
