<script setup lang="ts">
// The small mark at the top of the candidate screens. Plain SVG, no image to download.
</script>

<template>
  <div class="brand">
    <svg class="logo" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" />
      <path d="M9 16.5l4.6 4.6L23 11.5" />
    </svg>
    <span>Aptitude test</span>
  </div>
</template>

<style scoped>
.brand {
  display: inline-flex;
  gap: 0.6rem;
  align-items: center;
  margin-bottom: 1.25rem;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.logo {
  width: 1.75rem;
  height: 1.75rem;
}

.logo rect {
  fill: var(--accent);
}

.logo path {
  fill: none;
  stroke: var(--on-accent);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
