/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" serves the endpoints the backend does not have yet from fixtures (dev only). */
  readonly VITE_MOCK_API?: string
  /** "off" leaves out the microphone step of the pre-check (testing only). */
  readonly VITE_MIC_CHECK?: string
  /** "off" leaves out the full-screen step and cover (automated browser runs only). */
  readonly VITE_FULLSCREEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
