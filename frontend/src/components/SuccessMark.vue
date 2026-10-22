<script setup lang="ts">
// A green tick that draws itself. It appears at moments a candidate meets rarely (a step done,
// the test finished), which is where a little motion is worth having. With reduced motion it
// simply appears.
</script>

<template>
  <svg class="success" viewBox="0 0 48 48" aria-hidden="true">
    <circle class="ring" cx="24" cy="24" r="21" />
    <path class="tick" d="M14.5 25l7 7L34 17" />
  </svg>
</template>

<style scoped>
.success {
  width: 3.25rem;
  height: 3.25rem;
}

.ring {
  fill: var(--ok-tint);
  stroke: var(--ok);
  stroke-width: 2.5;
  transform-origin: center;
  animation: pop 320ms var(--ease-out) both;
}

.tick {
  fill: none;
  stroke: var(--ok);
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 32;
  stroke-dashoffset: 32;
  animation: draw 380ms var(--ease-out) 140ms forwards;
}

@keyframes pop {
  from {
    opacity: 0;
    transform: scale(0.85);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ring {
    animation: none;
  }

  .tick {
    animation: none;
    stroke-dashoffset: 0;
  }
}
</style>
