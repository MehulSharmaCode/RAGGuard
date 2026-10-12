/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public base URL of the RAGGuard API. Never put secrets in VITE_* variables. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
