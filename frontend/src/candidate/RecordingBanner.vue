<script setup lang="ts">
import { useRecordingState } from '../composables/useRecordingState'
import { CAMERA_LOST_BANNER } from './copy'

/**
 * Shown above the question while the camera or microphone is lost and being reconnected. It never
 * blocks: the question stays answerable and the clock keeps running, because the server's clock is
 * the one that counts.
 */
const recording = useRecordingState()
</script>

<template>
  <!-- The live region stays mounted so a screen reader announces the text when it appears. -->
  <div role="status">
    <p v-if="recording === 'lost'" class="banner">{{ CAMERA_LOST_BANNER }}</p>
  </div>
</template>
