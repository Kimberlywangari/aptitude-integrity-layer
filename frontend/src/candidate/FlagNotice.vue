<script setup lang="ts">
import Icon from '../components/Icon.vue'
import { noticeVisible } from '../lib/flagNotice'
import { FLAG_NOTICE } from './copy'
</script>

<template>
  <!-- A polite status line at the foot of the screen. It never takes focus, never blocks a click
       and never touches the question clock. -->
  <Transition name="notice">
    <div v-if="noticeVisible" class="flag-notice" role="status">
      <Icon name="info" size="1.1em" />
      <p>{{ FLAG_NOTICE }}</p>
    </div>
  </Transition>
</template>

<style scoped>
.flag-notice {
  position: fixed;
  right: 0;
  bottom: 1rem;
  left: 0;
  z-index: 5;
  display: flex;
  gap: 0.6rem;
  align-items: center;
  width: fit-content;
  max-width: calc(100% - 2rem);
  padding: 0.65rem 0.9rem;
  margin: 0 auto;
  color: var(--text);
  pointer-events: none;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
}

.flag-notice p {
  margin: 0;
  font-size: 0.9rem;
}

/* The test screen only fades; about 120 ms, and not at all for someone who asks for less motion. */
.notice-enter-active,
.notice-leave-active {
  transition: opacity 120ms var(--ease-out);
}

.notice-enter-from,
.notice-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .notice-enter-active,
  .notice-leave-active {
    transition: none;
  }
}
</style>
