// The background work of a test, started and ended from the screens in one call each, so a screen
// never has to know which of the pieces are involved.
//
//   prepareRecording  "I agree, start the test": the log, the recorder and the uploader begin, and
//                     the answer says whether the server has seen a real recording yet
//   startTestRuntime  the test page: heartbeat, action logger, microphone watch, and the camera
//                     again if a reload took it away
//   endTestRuntime    the finish page: those stop, and the log is sent in full

import { startActionLogger } from './actionLogger'
import { acquireDevices } from './devices'
import { flushEvents, startEventLog } from './eventLog'
import { startHeartbeat } from './heartbeat'
import { heldDevices } from './media'
import { startMicWatch } from './micWatch'
import {
  ensureRecording,
  recordingState,
  RecorderUnsupportedError,
  startRecording,
} from './recording'
import { startUploader, waitForUploads } from './uploader'

/** How long the test may wait for the first chunk to reach the server. */
export const FIRST_UPLOAD_WAIT_MS = 30_000

export type PrepareResult =
  | 'ready' // a real recording has reached the server
  | 'slow' // recording, but nothing has arrived yet: try again
  | 'no_devices' // the camera and microphone could not be had
  | 'unsupported' // this browser cannot record

export async function prepareRecording(sessionId: string): Promise<PrepareResult> {
  startEventLog(sessionId)

  if (recordingState() === 'off') {
    let handle = heldDevices()
    try {
      handle ??= await acquireDevices()
    } catch {
      return 'no_devices'
    }
    try {
      await startRecording(sessionId, handle)
    } catch (error) {
      handle.stop()
      return error instanceof RecorderUnsupportedError ? 'unsupported' : 'no_devices'
    }
  }

  startUploader(sessionId)
  return (await waitForUploads(1, FIRST_UPLOAD_WAIT_MS)) ? 'ready' : 'slow'
}

let stops: (() => void)[] = []

export function startTestRuntime(sessionId: string): void {
  startEventLog(sessionId)
  if (stops.length === 0) stops = [startActionLogger(), startHeartbeat(), startMicWatch()]
  startUploader(sessionId)
  void ensureRecording(sessionId)
}

/** Call after the recording has been stopped (`stopRecording` gives the number `finish` needs). */
export async function endTestRuntime(): Promise<void> {
  stops.forEach((stop) => stop())
  stops = []
  await flushEvents()
}
