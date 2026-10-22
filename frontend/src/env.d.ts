/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "off" leaves out the microphone step of the pre-check (testing only). */
  readonly VITE_MIC_CHECK?: string
  /** "off" leaves out the full-screen step and cover (automated browser runs only). */
  readonly VITE_FULLSCREEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
