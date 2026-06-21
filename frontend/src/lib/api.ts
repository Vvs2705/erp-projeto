// Cliente HTTP central do ERP-V.
//
// A base da API vem de VITE_API_URL (injetada no build do Vercel). Em
// desenvolvimento, cai para o backend local. Nunca embuta segredos aqui — só a
// URL pública do serviço.
import { useAuthStore } from '../store/authStore'

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
  // Quando true, anexa automaticamente o access token do store e, em 401,
  // encerra a sessão (token expirado/revogado).
  auth?: boolean
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = opts.auth ? useAuthStore.getState().token : opts.token
  if (token) {
    headers.Authorization = `Bearer ${token}`
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
    // Token expirado/revogado numa rota autenticada → desloga.
    if (res.status === 401 && opts.auth) {
      useAuthStore.getState().logout()
    }
    const detail =
      (data && typeof data.detail === 'string' && data.detail) ||
      `Erro ${res.status}`
    throw new ApiError(res.status, detail)
  }
  return data as T
}

// ─── Auth ───
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

// ─── Reporting / Analytics (KPIs e fluxo de caixa reais) ───
// O backend serializa Decimal como string (ex.: "0.0000"). Tipamos como
// number | string e coagimos no frontend.
export type Decimalish = number | string

export interface FinancialKpis {
  period: { start_date: string; end_date: string }
  result: {
    gross_revenue: Decimalish
    total_expenses: Decimalish
    net_result: Decimalish
    net_margin: Decimalish
  }
  position: {
    total_assets: Decimalish
    total_liabilities: Decimalish
    total_equity: Decimalish
    debt_ratio: Decimalish
    equity_ratio: Decimalish
  }
  returns: { return_on_assets: Decimalish; return_on_equity: Decimalish }
  working_capital: {
    accounts_receivable_open: Decimalish
    accounts_payable_open: Decimalish
    net_working_capital: Decimalish
  }
}

export interface CashFlow {
  start_date: string
  end_date: string
  operating: {
    receipts_from_customers: Decimalish
    payments_to_suppliers: Decimalish
    net_cash_from_operations: Decimalish
  }
  by_method: {
    inflows: Record<string, Decimalish>
    outflows: Record<string, Decimalish>
  }
  net_cash_flow: Decimalish
}

export const reportingApi = {
  kpis(startDate: string, endDate: string) {
    return request<FinancialKpis>(
      `/api/v1/reporting/kpis?start_date=${startDate}&end_date=${endDate}`,
      { auth: true },
    )
  },
  cashFlow(startDate: string, endDate: string) {
    return request<CashFlow>(
      `/api/v1/reporting/cash-flow?start_date=${startDate}&end_date=${endDate}`,
      { auth: true },
    )
  },
}

// ─── Fiscal (calculadora de tributos — determinação real por vigência) ───
export type FiscalRegime = 'simples_nacional' | 'lucro_presumido' | 'lucro_real'

export interface FiscalCalcRequest {
  amount: number
  issue_date: string
  is_service: boolean
  regime: FiscalRegime
}

// tributo -> valor (string), inclui total_taxes
export type FiscalCalcResponse = Record<string, string>

export const fiscalApi = {
  calculate(payload: FiscalCalcRequest) {
    return request<FiscalCalcResponse>('/api/v1/fiscal/calculate', {
      method: 'POST',
      body: payload,
      auth: true,
    })
  },
}

export { API_BASE }
