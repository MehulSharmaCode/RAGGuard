/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public base URL of the RAGGuard API. Never put secrets in VITE_* variables. */
  readonly VITE_API_BASE_URL?: string;
  /** Public `owner/name` whose GitHub Actions runs the Pipeline view lists. Never a token. */
  readonly VITE_GITHUB_REPOSITORY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
