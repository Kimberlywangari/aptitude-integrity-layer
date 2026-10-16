<script lang="ts">
/** What the reviewer asked for. `nonce` changes on every click so the same flag can be re-played. */
export type JumpTarget =
  | { kind: 'seek'; segment: number; seekS: number; label: string; nonce: number }
  | { kind: 'none'; label: string; nonce: number }
</script>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import BaseButton from '../components/BaseButton.vue'
import { formatDateTime, formatElapsed } from '../lib/format'
import type { VideoSegment } from '../lib/reviewTypes'

const props = defineProps<{
  segments: VideoSegment[]
  target: JumpTarget | null
  deletedAt: string | null
}>()

const video = ref<HTMLVideoElement | null>(null)
const active = ref(0)
let pendingSeek: number | null = null

// A new jump to another part switches to it (the element below is keyed on the part, so it is a
// fresh <video> that has to load before it can seek). Seek at once when the right part is already
// loaded; otherwise onLoadedMetadata does it.
watch(
  () => props.target,
  async (target) => {
    if (target?.kind !== 'seek') return
    pendingSeek = target.seekS
    active.value = target.segment
    await nextTick()
    const element = video.value
    if (element && element.readyState >= 1) {
      element.currentTime = target.seekS
      pendingSeek = null
    }
  },
  { immediate: true },
)

function onLoadedMetadata() {
  if (pendingSeek !== null && video.value) {
    video.value.currentTime = pendingSeek
    pendingSeek = null
  }
}

const segment = computed(() => props.segments.find((s) => s.segment === active.value) ?? props.segments[0])
</script>

<template>
  <div v-if="deletedAt" class="panel">
    <h2>Video</h2>
    <p>
      The video was deleted on {{ formatDateTime(deletedAt) }}, 30 days after the decision. The
      flags and the packet above are kept.
    </p>
  </div>

  <div v-else-if="segments.length === 0" class="panel">
    <h2>Video</h2>
    <p>No video was recorded for this candidate.</p>
  </div>

  <div v-else class="panel">
    <h2>Video</h2>
    <div v-if="segments.length > 1" class="actions" role="group" aria-label="Recording part">
      <BaseButton
        v-for="s in segments"
        :key="s.segment"
        :variant="s.segment === segment.segment ? 'primary' : 'secondary'"
        @click="active = s.segment"
      >
        Part {{ s.segment + 1 }}
      </BaseButton>
    </div>

    <video
      v-if="segment.url"
      :key="segment.segment"
      ref="video"
      :src="segment.url"
      controls
      preload="metadata"
      @loadedmetadata="onLoadedMetadata"
    />
    <div v-else class="video-placeholder">
      The video file is not available here (sample data). Jumps still show where the player would
      land.
    </div>

    <p role="status" class="muted">
      <template v-if="target?.kind === 'seek'">
        {{ target.label }}: part {{ target.segment + 1 }} at {{ formatElapsed(target.seekS) }},
        starting 5 s before the moment.
      </template>
      <template v-else-if="target?.kind === 'none'">
        {{ target.label }}: no video was recorded at this moment (a camera drop or an incomplete
        upload).
      </template>
      <template v-else>Choose a flag to jump to the moment, starting 5 s before it.</template>
    </p>
  </div>
</template>
