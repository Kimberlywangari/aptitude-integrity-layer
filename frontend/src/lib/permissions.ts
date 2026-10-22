// What the browser currently allows for this site, read from the Permissions API. Chrome and Edge
// both answer for "camera" and "microphone". A browser that does not answer reports 'unknown', and
// the pre-check then learns the truth by asking (getUserMedia) instead.

export type DevicePermission = 'camera' | 'microphone'
export type PermissionState = 'granted' | 'denied' | 'prompt' | 'unknown'

function query(name: DevicePermission): Promise<PermissionStatus> {
  return navigator.permissions.query({ name } as unknown as PermissionDescriptor)
}

export async function queryPermission(name: DevicePermission): Promise<PermissionState> {
  try {
    return (await query(name)).state
  } catch {
    return 'unknown'
  }
}

/**
 * Calls back when the candidate changes the setting from the address bar while the page is open.
 * Returns a function that stops listening (already stopped if the browser could not answer).
 */
export async function watchPermission(
  name: DevicePermission,
  callback: (state: PermissionState) => void,
): Promise<() => void> {
  try {
    const status = await query(name)
    const handler = () => callback(status.state)
    status.addEventListener('change', handler)
    return () => status.removeEventListener('change', handler)
  } catch {
    return () => undefined
  }
}

/** The worse of two answers: blocked beats not-asked-yet beats allowed. */
export function combine(a: PermissionState, b: PermissionState): PermissionState {
  const order: PermissionState[] = ['denied', 'prompt', 'unknown', 'granted']
  return order[Math.min(order.indexOf(a), order.indexOf(b))]
}
