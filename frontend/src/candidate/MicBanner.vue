<script setup lang="ts">
import { useMicSilent } from '../composables/useMicSilent'
import { micCheckEnabled } from '../lib/features'
import { MIC_BANNER } from './copy'

/**
 * Warning shown above the question while the microphone looks muted or silent. It never blocks:
 * no button is disabled, the countdown keeps running and no request changes.
 */
const silent = useMicSilent()
// The warning belongs to the microphone check: nothing to show while that check is switched off.
const enabled = micCheckEnabled()
</script>

<template>
  <!-- The live region stays mounted so a screen reader announces the text when it appears. -->
  <div v-if="enabled" role="status">
    <p v-if="silent" class="banner">{{ MIC_BANNER }}</p>
  </div>
</template>
