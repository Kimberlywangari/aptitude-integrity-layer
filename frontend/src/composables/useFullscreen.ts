import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  enterFullscreen,
  fullscreenSupported,
  isFullscreen,
  leaveFullscreen,
  onFullscreenChange,
} from '../lib/fullscreen'

/** Whether the page is in full screen right now, kept up to date while the component is mounted. */
export function useFullscreen() {
  const active = ref(isFullscreen())
  let stop: (() => void) | null = null

  onMounted(() => {
    active.value = isFullscreen()
    stop = onFullscreenChange((full) => {
      active.value = full
    })
  })
  onBeforeUnmount(() => stop?.())

  return { active, supported: fullscreenSupported(), enter: enterFullscreen, leave: leaveFullscreen }
}
