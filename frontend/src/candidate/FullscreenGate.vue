<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Banner from '../components/Banner.vue'
import BaseButton from '../components/BaseButton.vue'
import Icon from '../components/Icon.vue'
import { enterFullscreen } from '../lib/fullscreen'
import { FULLSCREEN_COVER_BODY, FULLSCREEN_COVER_TITLE } from './copy'

/**
 * Covers the question while the page is not full screen. A page cannot stop a candidate leaving
 * full screen, so this does the next best thing: it hides the question until they return, and
 * says plainly that the clock has not stopped. The exit itself is logged as context for the
 * reviewer, never as a flag (master plan 7.3).
 */
defineProps<{ timeLeft: string }>()

const failed = ref(false)
const button = ref<{ $el: HTMLButtonElement } | null>(null)

// The browser only allows full screen from a click, so this must run in the click handler.
async function comeBack() {
  failed.value = !(await enterFullscreen())
}

onMounted(() => button.value?.$el.focus())
</script>

<template>
  <div class="cover" role="dialog" aria-modal="true" aria-labelledby="fullscreen-title">
    <div class="sheet">
      <span class="badge-icon"><Icon name="fullscreen" size="1.6rem" /></span>
      <h2 id="fullscreen-title">{{ FULLSCREEN_COVER_TITLE }}</h2>
      <p>{{ FULLSCREEN_COVER_BODY }}</p>
      <p class="time">
        Time left <strong>{{ timeLeft }}</strong>
      </p>
      <BaseButton ref="button" size="lg" block @click="comeBack">Return to full screen</BaseButton>
      <Banner v-if="failed" tone="bad" role="alert">
        <p>Your browser did not switch to full screen. Press the button again.</p>
      </Banner>
    </div>
  </div>
</template>

<style scoped>
.cover {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: 1.25rem;
  background: color-mix(in srgb, var(--bg) 93%, transparent);
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
}

.sheet {
  width: 100%;
  max-width: 26rem;
  padding: 1.6rem 1.5rem;
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
}

.badge-icon {
  display: inline-grid;
  place-items: center;
  width: 3.25rem;
  height: 3.25rem;
  margin-bottom: 0.75rem;
  color: var(--accent);
  background: var(--accent-tint);
  border-radius: 50%;
}

.time {
  font-variant-numeric: tabular-nums;
}

/* A modal is not anchored to a trigger, so it grows from its own centre. */
.cover-enter-active,
.cover-leave-active {
  transition: opacity 160ms var(--ease-out);
}

.cover-enter-active .sheet {
  transition: transform 160ms var(--ease-out);
}

.cover-enter-from {
  opacity: 0;
}

.cover-enter-from .sheet {
  transform: scale(0.97);
}

.cover-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .cover-enter-active .sheet {
    transition: none;
  }

  .cover-enter-from .sheet {
    transform: none;
  }
}
</style>
