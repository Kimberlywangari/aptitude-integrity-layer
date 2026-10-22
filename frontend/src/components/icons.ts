// Stroke icons drawn inline (24 x 24 grid), so there is no icon font or image to download.

export const ICON_PATHS = {
  check: ['M5 12.5l4.5 4.5L19 7.5'],
  alert: ['M12 4l9 16H3L12 4z', 'M12 10v4', 'M12 17.2v.01'],
  info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v5', 'M12 7.8v.01'],
  camera: [
    'M4 8a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8z',
    'M16 10.5l5-3v9l-5-3',
  ],
  mic: [
    'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z',
    'M6 11a6 6 0 0 0 12 0',
    'M12 17v4',
    'M9 21h6',
  ],
  fullscreen: ['M4 9V4h5', 'M20 9V4h-5', 'M4 15v5h5', 'M20 15v5h-5'],
  'bell-off': [
    'M6 8a6 6 0 0 1 9.5-4.9',
    'M18 8c0 4 1 6 2 7H5',
    'M10 19a2 2 0 0 0 4 0',
    'M3 3l18 18',
  ],
  sun: [
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
    'M12 2v2',
    'M12 20v2',
    'M2 12h2',
    'M20 12h2',
    'M4.9 4.9l1.4 1.4',
    'M17.7 17.7l1.4 1.4',
    'M4.9 19.1l1.4-1.4',
    'M17.7 6.3l1.4-1.4',
  ],
  moon: ['M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z'],
  'arrow-right': ['M5 12h14', 'M13 6l6 6-6 6'],
  clock: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 7v5l3 2'],
  shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z', 'M8.5 12l2.5 2.5L15.5 10'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21a8 8 0 0 1 16 0'],
  clipboard: [
    'M9 4h6v3H9z',
    'M7 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-1',
    'M8 12h8',
    'M8 16h5',
  ],
  sliders: ['M4 7h10', 'M18 7h2', 'M4 17h2', 'M10 17h10', 'M14 5v4', 'M6 15v4'],
  upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M5 20h14'],
  lock: ['M6 11h12v9H6z', 'M8 11V8a4 4 0 0 1 8 0v3'],
  grid: ['M4 4h7v9H4z', 'M13 4h7v5h-7z', 'M13 11h7v9h-7z', 'M4 15h7v5H4z'],
  queue: ['M4 6h16', 'M4 12h9', 'M4 18h6', 'M17.5 14.5a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', 'M19.7 20.7L22 23'],
} as const

export type IconName = keyof typeof ICON_PATHS
