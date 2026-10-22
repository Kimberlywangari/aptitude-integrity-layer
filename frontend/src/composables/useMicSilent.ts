import { onScopeDispose, ref } from 'vue'
import { getMicSilent, subscribeMicSilent } from '../lib/micStatus'

/** True while the microphone looks muted or silent (set by the level watch, master plan 7.8). */
export function useMicSilent() {
  const silent = ref(getMicSilent())
  const stop = subscribeMicSilent(() => {
    silent.value = getMicSilent()
  })
  onScopeDispose(stop)
  return silent
}
