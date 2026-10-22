<script setup lang="ts">
import type { Band } from '../lib/reviewTypes'
import { BAND_LABELS } from './copy'

// The words carry the meaning, the colour only helps: "High" is readable without it.
withDefaults(defineProps<{ band: Band; long?: boolean }>(), { long: false })
</script>

<template>
  <span class="pill" :class="band">{{ BAND_LABELS[band] }}<template v-if="long"> priority</template></span>
</template>
