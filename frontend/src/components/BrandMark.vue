<script setup lang="ts">
// The logo at the top of the screens, on a white backing so it reads in the dark theme too.
import logo from '../assets/cytonn-logo.png'

defineProps<{ compact?: boolean }>()
</script>

<template>
  <div class="brand" :class="{ compact }">
    <img :src="logo" alt="Cytonn: delivering to promise" width="500" height="307" />
  </div>
</template>

<style scoped>
.brand {
  display: inline-block;
  margin-bottom: 1.25rem;
  line-height: 0;
  background: var(--logo-backing);
  border-radius: 0.5rem;
}

.brand img {
  width: auto;
  height: 5rem;
  mix-blend-mode: multiply; /* light theme: the white ground takes the page colour */
}

.brand.compact {
  margin-bottom: 0;
}

.brand.compact img {
  height: 2.4rem;
}
</style>
