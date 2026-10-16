<script setup lang="ts">
import ThemeToggle from './components/ThemeToggle.vue'
</script>

<template>
  <!-- Mounted once, outside the routes, so every page has the light/dark toggle. -->
  <ThemeToggle />
  <RouterView />
</template>
