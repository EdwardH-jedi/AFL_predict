/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_REFRESH_TODAY_MS?: string;
  readonly VITE_REFRESH_STATUS_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
