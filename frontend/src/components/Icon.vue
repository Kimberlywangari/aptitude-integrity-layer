<script setup lang="ts">
import { computed } from 'vue'
import { ICON_PATHS } from './icons'
import type { IconName } from './icons'

const props = withDefaults(defineProps<{ name: IconName; size?: string }>(), { size: '1.25em' })
const paths = computed(() => ICON_PATHS[props.name])
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="d in paths" :key="d" :d="d" />
  </svg>
</template>

<style scoped>
.icon {
  flex: none;
}
</style>
