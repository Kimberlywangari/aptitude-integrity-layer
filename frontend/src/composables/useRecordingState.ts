import { onScopeDispose, ref } from 'vue'
import { onRecordingState, recordingState } from '../lib/recording'
import type { RecordingState } from '../lib/recording'

/** Whether the recording is going, starting, lost (being reconnected) or off. */
export function useRecordingState() {
  const state = ref<RecordingState>(recordingState())
  const stop = onRecordingState(() => {
    state.value = recordingState()
  })
  onScopeDispose(stop)
  return state
}
