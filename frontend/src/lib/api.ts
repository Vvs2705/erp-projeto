// Cliente HTTP central do ERP-V.
//
// A base da API vem de VITE_API_URL (injetada no build do Vercel). Em
// desenvolvimento, cai para o backend local. Nunca embuta segredos aqui — só a
// URL pública do serviço.
const API_BASE = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  token?: string | null
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (opts.token) {
    headers.Authorization = `Bearer ${opts.token}`
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'Não foi possível contatar o servidor. Verifique sua conexão.')
  }

  if (res.status === 204) {
    return undefined as T
  }

  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const detail =
      (data && typeof data.detail === 'string' && data.detail) ||
      `Erro ${res.status}`
    throw new ApiError(res.status, detail)
  }
  return data as T
}

// ─── Contratos da API (espelham os schemas Pydantic do backend) ───
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface MeResponse {
  user_id: string
  tenant_id: string
  permissions: string[]
}

export const authApi = {
  login(email: string, password: string, tenantSlug: string) {
    return request<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: { email, password, tenant_slug: tenantSlug },
    })
  },
  me(token: string) {
    return request<MeResponse>('/api/v1/auth/me', { token })
  },
  refresh(refreshToken: string) {
    return request<TokenResponse>('/api/v1/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
    })
  },
  logout(refreshToken: string) {
    return request<void>('/api/v1/auth/logout', {
      method: 'POST',
      body: { refresh_token: refreshToken },
    })
  },
}

export { API_BASE }
