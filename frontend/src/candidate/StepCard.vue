<script setup lang="ts">
import Icon from '../components/Icon.vue'

/**
 * One step of the pre-check. Done steps fold down to a line, the current step is open, and later
 * steps wait. The current heading takes focus when the step changes (id "step-heading").
 */
defineProps<{
  index: number
  title: string
  state: 'done' | 'current' | 'todo'
  summary?: string
}>()
</script>

<template>
  <li class="step" :class="state" :aria-current="state === 'current' ? 'step' : undefined">
    <span class="num" aria-hidden="true">
      <Icon v-if="state === 'done'" name="check" size="1rem" />
      <template v-else>{{ index }}</template>
    </span>
    <div class="main">
      <h2 :id="state === 'current' ? 'step-heading' : undefined" :tabindex="state === 'current' ? -1 : undefined">
        {{ title }}<span v-if="state === 'done'" class="sr-only"> (done)</span>
      </h2>
      <p v-if="state === 'done' && summary" class="muted summary">{{ summary }}</p>
      <div v-if="state === 'current'" class="body"><slot /></div>
    </div>
  </li>
</template>

<style scoped>
.step {
  position: relative;
  display: flex;
  gap: 0.9rem;
  padding-bottom: 1.1rem;
}

/* The line that joins one step to the next. */
.step:not(:last-child)::before {
  content: '';
  position: absolute;
  top: 2rem;
  bottom: 0.15rem;
  left: 0.9rem;
  width: 2px;
  background: var(--line-soft);
}

.num {
  position: relative;
  z-index: 1;
  display: grid;
  flex: none;
  place-items: center;
  width: 1.85rem;
  height: 1.85rem;
  font-size: 0.9rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  background: var(--surface);
  border: 2px solid var(--line);
  border-radius: 50%;
  transition:
    background-color 200ms var(--ease-out),
    border-color 200ms var(--ease-out),
    color 200ms var(--ease-out);
}

.current .num {
  color: var(--on-accent);
  background: var(--accent);
  border-color: var(--accent);
}

.done .num {
  color: var(--on-accent);
  background: var(--ok);
  border-color: var(--ok);
}

.main {
  flex: 1;
  min-width: 0;
}

h2 {
  margin: 0.2rem 0 0;
  font-size: 1.05rem;
  outline: none;
}

.todo h2 {
  color: var(--muted);
  font-weight: 500;
}

.summary {
  margin: 0.1rem 0 0;
}

.body {
  margin-top: 0.75rem;
  animation: rise 240ms var(--ease-out) both;
}
</style>
