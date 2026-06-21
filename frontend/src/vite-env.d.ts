/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL pública da API do backend (Fly.io). Injetada no build pelo Vercel. */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
