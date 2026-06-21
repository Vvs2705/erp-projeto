import React, { useState, useMemo } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useAuthStore } from './store/authStore'
import { authApi, ApiError, reportingApi, fiscalApi } from './lib/api'
import type { FiscalRegime, FiscalCalcResponse } from './lib/api'
import {
  LayoutDashboard,
  FileSpreadsheet,
  Users,
  Settings,
  LogOut,
  Search,
  Bell,
  Building2,
  TrendingUp,
  DollarSign,
  AlertTriangle,
  Menu,
  X,
  Loader2,
  Calculator,
  Wallet,
  RefreshCw
} from 'lucide-react'

// ─── Helpers de formatação (pt-BR) ───
// O backend manda Decimal como string; coage com segurança.
const num = (v: number | string | undefined | null): number => {
  const n = typeof v === 'number' ? v : parseFloat(v ?? '')
  return Number.isFinite(n) ? n : 0
}
const brl = (v: number | string) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(num(v))
const pct = (ratio: number | string) => `${(num(ratio) * 100).toFixed(1)}%`
const todayISO = () => new Date().toISOString().slice(0, 10)

// Auth Guard to protect private pages
function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

// Login Component
function Login() {
  const [subdomain, setSubdomain] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const login = useAuthStore((state) => state.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!subdomain) {
      setErrorMsg('Por favor, informe o subdomínio da sua empresa.')
      return
    }
    if (!email || !password) {
      setErrorMsg('Preencha o e-mail e a senha.')
      return
    }

    setLoading(true)
    setErrorMsg('')

    // O subdomínio digitado corresponde ao slug do tenant no backend.
    const slug = subdomain.split('.')[0].trim().toLowerCase()

    try {
      const tokens = await authApi.login(email, password, slug)
      const me = await authApi.me(tokens.access_token)

      login(
        { token: tokens.access_token, refreshToken: tokens.refresh_token },
        {
          id: me.user_id,
          name: email.split('@')[0],
          email,
          role: 'admin',
        },
        {
          id: me.tenant_id,
          name: slug.toUpperCase() + ' CORP',
          subdomain: subdomain.includes('.') ? subdomain : `${slug}.erp-v.com`,
          plan: 'enterprise',
        },
        me.permissions,
      )
      navigate('/')
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(
          err.status === 401
            ? 'Credenciais inválidas. Verifique e-mail, senha e subdomínio.'
            : err.status === 423
              ? 'Conta temporariamente bloqueada por excesso de tentativas. Tente mais tarde.'
              : err.message,
        )
      } else {
        setErrorMsg('Falha inesperada ao entrar. Tente novamente.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(74,111,165,0.15),rgba(255,255,255,0))] px-4">
      <div className="w-full max-w-md animate-gradient">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-500 text-white shadow-[0_0_20px_rgba(74,111,165,0.4)]">
            <Building2 className="h-6 w-6" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-white">ERP-V</h1>
          <p className="text-sm text-slate-400 mt-1 font-sans">Plataforma ERP Corporativa Multitenant</p>
        </div>

        {/* Card */}
        <div className="glass-panel p-8 rounded-2xl shadow-xl">
          <h2 className="text-xl font-semibold text-white mb-6">Acesse sua conta</h2>

          {errorMsg && (
            <div className="mb-4 p-3 bg-red-950/50 border border-red-800 text-red-300 text-sm rounded-lg flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">
                Subdomínio da Empresa
              </label>
              <div className="relative">
                <input
                  type="text"
                  placeholder="empresa"
                  value={subdomain}
                  onChange={(e) => setSubdomain(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent text-sm transition-all"
                />
                <span className="absolute right-3 top-2 text-sm text-slate-500 font-mono select-none">
                  .erp-v.com
                </span>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">
                E-mail
              </label>
              <input
                type="email"
                placeholder="nome@empresa.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent text-sm transition-all"
              />
            </div>

            <div>
              <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">
                Senha
              </label>
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent text-sm transition-all"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="glow-btn w-full mt-6 bg-brand-500 hover:bg-brand-600 text-white font-medium py-2.5 px-4 rounded-lg text-sm shadow-lg shadow-brand-500/20 transition-all flex justify-center items-center gap-2 cursor-pointer"
            >
              {loading ? (
                <>
                  <Loader2 className="animate-spin h-5 w-5" />
                  Conectando...
                </>
              ) : (
                'Entrar no ERP-V'
              )}
            </button>
          </form>

          <div className="mt-6 border-t border-slate-900 pt-4 text-center">
            <span className="text-xs text-slate-500 select-none">
              Ambiente Seguro e Homologado
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function KpiCard({ title, value, icon: Icon, loading }: { title: string; value: string; icon: React.ComponentType<{ className?: string }>; loading: boolean }) {
  return (
    <div className="glass-panel p-5 rounded-xl border border-slate-800 flex flex-col justify-between min-h-[116px]">
      <div className="flex justify-between items-start">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</span>
        <div className="p-2 rounded-lg bg-brand-950 border border-brand-900/50 text-brand-400">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <div className="mt-4">
        {loading ? (
          <div className="h-7 w-28 bg-slate-800/70 rounded animate-pulse" />
        ) : (
          <span className="text-2xl font-bold text-white">{value}</span>
        )}
      </div>
    </div>
  )
}

function PositionRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-slate-900 pb-2">
      <span className="text-slate-400">{label}</span>
      <span className="text-white font-mono">{value}</span>
    </div>
  )
}

// Dashboard — KPIs e fluxo de caixa REAIS (backend /api/v1/reporting).
function DashboardView() {
  const year = useMemo(() => new Date().getFullYear(), [])
  const startDate = `${year}-01-01`
  const endDate = useMemo(() => todayISO(), [])

  const kpis = useQuery({
    queryKey: ['kpis', startDate, endDate],
    queryFn: () => reportingApi.kpis(startDate, endDate),
  })
  const cash = useQuery({
    queryKey: ['cashflow', startDate, endDate],
    queryFn: () => reportingApi.cashFlow(startDate, endDate),
  })

  const loading = kpis.isLoading || cash.isLoading
  const error = (kpis.error || cash.error) as Error | null
  const emptyCash =
    !loading &&
    cash.data &&
    num(cash.data.operating.receipts_from_customers) === 0 &&
    num(cash.data.operating.payments_to_suppliers) === 0

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white">Olá, Bem-vindo de Volta</h2>
          <p className="text-slate-400 text-sm">
            Indicadores reais do exercício {year} (1º jan — hoje), apurados do razão contábil.
          </p>
        </div>
        <button
          onClick={() => { void kpis.refetch(); void cash.refetch() }}
          className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 border border-slate-800 rounded-lg px-3 py-1.5 shrink-0 cursor-pointer"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Atualizar
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-950/50 border border-red-800 text-red-300 text-sm rounded-lg flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>Falha ao carregar indicadores: {error.message}</span>
        </div>
      )}

      {/* KPI cards — dados reais */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard title="Faturamento Bruto" icon={DollarSign} loading={loading} value={kpis.data ? brl(kpis.data.result.gross_revenue) : '—'} />
        <KpiCard title="Resultado Líquido" icon={TrendingUp} loading={loading} value={kpis.data ? brl(kpis.data.result.net_result) : '—'} />
        <KpiCard title="Margem Líquida" icon={TrendingUp} loading={loading} value={kpis.data ? pct(kpis.data.result.net_margin) : '—'} />
        <KpiCard title="A Receber em Aberto" icon={FileSpreadsheet} loading={loading} value={kpis.data ? brl(kpis.data.working_capital.accounts_receivable_open) : '—'} />
      </div>

      {/* Fluxo de caixa + posição patrimonial */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="glass-panel p-5 rounded-xl border border-slate-800 lg:col-span-2">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <Wallet className="h-4 w-4 text-brand-400" /> Fluxo de Caixa (método direto)
            </h3>
            <span className="text-[10px] text-slate-500 font-mono select-none">/reporting/cash-flow</span>
          </div>
          {loading ? (
            <div className="h-20 bg-slate-800/40 rounded animate-pulse" />
          ) : cash.data ? (
            <>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-xs text-slate-400">Recebimentos</p>
                  <p className="text-lg font-bold text-emerald-400">{brl(cash.data.operating.receipts_from_customers)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">Pagamentos</p>
                  <p className="text-lg font-bold text-rose-400">{brl(cash.data.operating.payments_to_suppliers)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">Caixa Líquido</p>
                  <p className="text-lg font-bold text-white">{brl(cash.data.net_cash_flow)}</p>
                </div>
              </div>
              {emptyCash && (
                <p className="mt-4 text-xs text-slate-500">
                  Sem movimentações de caixa no período. Conforme você registrar recebimentos e pagamentos, o fluxo aparece aqui automaticamente.
                </p>
              )}
            </>
          ) : null}
        </div>

        <div className="glass-panel p-5 rounded-xl border border-slate-800">
          <h3 className="font-semibold text-white mb-4">Posição Patrimonial</h3>
          {loading ? (
            <div className="space-y-3">{[0, 1, 2, 3].map((i) => <div key={i} className="h-5 bg-slate-800/50 rounded animate-pulse" />)}</div>
          ) : kpis.data ? (
            <div className="space-y-3 text-sm">
              <PositionRow label="Ativos" value={brl(kpis.data.position.total_assets)} />
              <PositionRow label="Passivos" value={brl(kpis.data.position.total_liabilities)} />
              <PositionRow label="Patrimônio Líquido" value={brl(kpis.data.position.total_equity)} />
              <PositionRow label="Endividamento" value={pct(kpis.data.position.debt_ratio)} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

const TAX_LABELS: Record<string, string> = {
  icms: 'ICMS',
  ipi: 'IPI',
  iss: 'ISS',
  pis: 'PIS',
  cofins: 'COFINS',
  cbs: 'CBS (RTC)',
  ibs: 'IBS (RTC)',
  total_taxes: 'Total de Tributos',
}

// Notas Fiscais — calculadora de tributos REAL (POST /api/v1/fiscal/calculate).
function InvoicesView() {
  const [amount, setAmount] = useState('1000.00')
  const [issueDate, setIssueDate] = useState(todayISO())
  const [isService, setIsService] = useState(false)
  const [regime, setRegime] = useState<FiscalRegime>('lucro_presumido')

  const calc = useMutation({
    mutationFn: () =>
      fiscalApi.calculate({
        amount: parseFloat(amount.replace(',', '.')) || 0,
        issue_date: issueDate,
        is_service: isService,
        regime,
      }),
  })

  const result: FiscalCalcResponse | undefined = calc.data
  const entries = result
    ? Object.entries(result).sort(([a], [b]) =>
        a === 'total_taxes' ? 1 : b === 'total_taxes' ? -1 : 0,
      )
    : []
  const calcError = calc.error as ApiError | null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const value = parseFloat(amount.replace(',', '.'))
    if (!value || value <= 0) return
    calc.mutate()
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Notas Fiscais & Tributação</h2>
        <p className="text-slate-400 text-sm">
          Determinação tributária real, versionada por vigência (inclui CBS/IBS da Reforma Tributária a partir de 2026).
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Formulário */}
        <form onSubmit={handleSubmit} className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
          <h3 className="font-semibold text-white flex items-center gap-2">
            <Calculator className="h-4 w-4 text-brand-400" /> Calculadora Fiscal
          </h3>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">Valor da operação (R$)</label>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">Data de emissão</label>
            <input
              type="date"
              value={issueDate}
              onChange={(e) => setIssueDate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">Tipo de operação</label>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setIsService(false)} className={`py-2 rounded-lg text-sm border transition-colors cursor-pointer ${!isService ? 'bg-brand-500/15 border-brand-500 text-brand-300' : 'border-slate-800 text-slate-400 hover:text-slate-200'}`}>Mercadoria</button>
              <button type="button" onClick={() => setIsService(true)} className={`py-2 rounded-lg text-sm border transition-colors cursor-pointer ${isService ? 'bg-brand-500/15 border-brand-500 text-brand-300' : 'border-slate-800 text-slate-400 hover:text-slate-200'}`}>Serviço</button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">Regime tributário</label>
            <select
              value={regime}
              onChange={(e) => setRegime(e.target.value as FiscalRegime)}
              className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="simples_nacional">Simples Nacional</option>
              <option value="lucro_presumido">Lucro Presumido</option>
              <option value="lucro_real">Lucro Real</option>
            </select>
          </div>

          <button
            type="submit"
            disabled={calc.isPending}
            className="glow-btn w-full bg-brand-500 hover:bg-brand-600 text-white font-medium py-2.5 rounded-lg text-sm shadow-lg shadow-brand-500/20 transition-all flex justify-center items-center gap-2 cursor-pointer"
          >
            {calc.isPending ? <><Loader2 className="animate-spin h-4 w-4" /> Calculando...</> : 'Calcular tributos'}
          </button>
        </form>

        {/* Resultado */}
        <div className="glass-panel p-6 rounded-xl border border-slate-800">
          <h3 className="font-semibold text-white mb-4">Tributos determinados</h3>

          {calcError && (
            <div className="p-3 bg-red-950/50 border border-red-800 text-red-300 text-sm rounded-lg flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{calcError.message}</span>
            </div>
          )}

          {!result && !calcError && (
            <div className="text-center py-10">
              <FileSpreadsheet className="h-10 w-10 mx-auto text-slate-600 mb-3" />
              <p className="text-slate-400 text-sm">Preencha os dados e clique em “Calcular tributos”.</p>
            </div>
          )}

          {result && (
            <div className="divide-y divide-slate-900">
              {entries.map(([tax, value]) => {
                const isTotal = tax === 'total_taxes'
                return (
                  <div key={tax} className={`flex justify-between py-2.5 ${isTotal ? 'mt-1 border-t-2 border-slate-800' : ''}`}>
                    <span className={isTotal ? 'font-semibold text-white' : 'text-slate-300'}>
                      {TAX_LABELS[tax] ?? tax.toUpperCase()}
                    </span>
                    <span className={`font-mono ${isTotal ? 'font-bold text-brand-300' : 'text-slate-200'}`}>
                      {brl(parseFloat(value))}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Nota: a <span className="text-slate-400">emissão</span> de DF-e (transmissão à SEFAZ) exige um provedor configurado no backend; sem ele, a emissão é recusada com erro claro. O cálculo acima é determinístico e não depende de provedor.
      </p>
    </div>
  )
}

// Clients view — estado honesto: backend ainda não expõe listagem/cadastro.
function ClientsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Clientes</h2>
        <p className="text-slate-400 text-sm">Controle de clientes corporativos e individuais (CRM / ERP).</p>
      </div>

      <div className="glass-panel p-10 rounded-xl border border-slate-800 text-center">
        <Users className="h-12 w-12 mx-auto text-slate-600 mb-4" />
        <h3 className="text-lg font-semibold text-white">Listagem de clientes em construção</h3>
        <p className="text-slate-400 text-sm mt-1 max-w-md mx-auto">
          O backend ainda não expõe um endpoint de listagem/cadastro de clientes — hoje o cliente é informado dentro de pedidos de venda. O próximo passo é adicionar
          <span className="font-mono text-slate-300"> GET /api/v1/customers</span> e ligar esta tela a ele.
        </p>
      </div>
    </div>
  )
}

// Settings view
function SettingsView() {
  const tenant = useAuthStore((state) => state.tenant)
  const user = useAuthStore((state) => state.user)
  const permissions = useAuthStore((state) => state.permissions)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Configurações Gerais</h2>
        <p className="text-slate-400 text-sm">Personalização, controle de inquilino e integrações com microsserviços.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
          <h3 className="font-semibold text-white border-b border-slate-900 pb-2">Informações da Organização (Tenant)</h3>

          <div className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">Nome Fantasia:</span>
              <span className="text-white font-medium">{tenant?.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">Subdomínio Identificador:</span>
              <span className="text-brand-400 font-mono">{tenant?.subdomain}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">Plano de Assinatura:</span>
              <span className="px-2 py-0.5 rounded bg-brand-950 text-brand-400 font-semibold border border-brand-900/40 uppercase text-[9px] select-none">
                {tenant?.plan}
              </span>
            </div>
          </div>
        </div>

        <div className="glass-panel p-6 rounded-xl border border-slate-800 space-y-4">
          <h3 className="font-semibold text-white border-b border-slate-900 pb-2">Perfil do Usuário Autenticado</h3>

          <div className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">E-mail:</span>
              <span className="text-white font-mono">{user?.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">Permissões ativas:</span>
              <span className="text-white font-medium">{permissions.length}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="glass-panel p-6 rounded-xl border border-slate-800">
        <h3 className="font-semibold text-white border-b border-slate-900 pb-2 mb-3">Permissões concedidas (do token)</h3>
        <div className="flex flex-wrap gap-2">
          {permissions.length === 0 && <span className="text-slate-500 text-xs">Nenhuma permissão carregada.</span>}
          {permissions.map((p) => (
            <span key={p} className="px-2 py-0.5 rounded bg-slate-900 text-slate-300 border border-slate-800 font-mono text-[10px]">{p}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// Main App Layout Wrapper
function DashboardLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const tenant = useAuthStore((state) => state.tenant)
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const refreshToken = useAuthStore((state) => state.refreshToken)
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    // Revoga o refresh token no servidor (best-effort) antes de limpar a sessão.
    if (refreshToken) {
      authApi.logout(refreshToken).catch(() => undefined)
    }
    logout()
    navigate('/login')
  }

  const navItems = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard, view: <DashboardView /> },
    { name: 'Notas Fiscais', path: '/notas', icon: FileSpreadsheet, view: <InvoicesView /> },
    { name: 'Clientes', path: '/clientes', icon: Users, view: <ClientsView /> },
    { name: 'Configurações', path: '/configuracoes', icon: Settings, view: <SettingsView /> }
  ]

  const activeItem = navItems.find((item) => item.path === location.pathname) || navItems[0]

  return (
    <div className="h-screen flex bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex flex-col w-64 bg-slate-950/80 border-r border-slate-900 shrink-0">
        {/* Brand Header */}
        <div className="h-16 flex items-center gap-3 px-6 border-b border-slate-900">
          <div className="h-8 w-8 rounded-lg bg-brand-500 flex items-center justify-center text-white shadow-[0_0_15px_rgba(74,111,165,0.3)] select-none">
            <Building2 className="h-4 w-4" />
          </div>
          <div>
            <h1 className="font-bold text-white tracking-wide leading-none select-none">ERP-V</h1>
            <span className="text-[10px] text-brand-400 font-mono tracking-tighter select-none">
              {tenant?.subdomain.split('.')[0]}
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 py-6 space-y-1">
          {navItems.map((item) => {
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                  isActive
                    ? 'bg-brand-500/10 text-brand-400 border-l-2 border-brand-500 font-medium'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
                }`}
              >
                <item.icon className="h-4.5 w-4.5 shrink-0" />
                <span>{item.name}</span>
              </Link>
            )
          })}
        </nav>

        {/* User Footer Session */}
        <div className="p-4 border-t border-slate-900 space-y-3">
          <div className="flex items-center gap-3 px-2">
            <div className="h-9 w-9 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400 font-bold font-mono select-none">
              VS
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-white truncate">{user?.name}</p>
              <p className="text-[10px] text-slate-500 truncate">{user?.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 py-1.5 px-3 bg-red-950/20 hover:bg-red-950/40 border border-red-900/20 hover:border-red-900/40 text-red-400 text-xs rounded-lg transition-colors font-medium cursor-pointer"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Sair da conta</span>
          </button>
        </div>
      </aside>

      {/* Main Layout Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top Navbar */}
        <header className="h-16 bg-slate-950/50 border-b border-slate-900 flex items-center justify-between px-6 shrink-0 backdrop-blur-md">
          {/* Mobile Hamburguer & Title */}
          <div className="flex items-center gap-3 lg:hidden">
            <button
              onClick={() => setMobileMenuOpen(true)}
              className="p-1.5 rounded-lg border border-slate-850 text-slate-400 hover:text-slate-200 cursor-pointer"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="font-bold text-white text-sm select-none">ERP-V</span>
          </div>

          {/* Search bar */}
          <div className="hidden md:flex items-center gap-2 bg-slate-900/50 border border-slate-800 rounded-lg px-3 py-1.5 w-80">
            <Search className="h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Pesquisar notas, clientes, ações..."
              className="bg-transparent border-none text-xs text-white placeholder-slate-600 focus:outline-none w-full"
            />
          </div>

          {/* Right Header Controls */}
          <div className="flex items-center gap-4">
            <button className="relative p-1.5 rounded-lg border border-slate-900 hover:border-slate-850 text-slate-400 hover:text-slate-200 transition-colors cursor-pointer">
              <Bell className="h-4 w-4" />
              <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-brand-500 ring-2 ring-slate-950"></span>
            </button>

            <div className="h-8 w-px bg-slate-900"></div>

            {/* Subdomain indicator */}
            <div className="flex items-center gap-2 bg-brand-950/50 border border-brand-900/30 px-3 py-1 rounded-lg text-xs text-brand-400 font-mono select-none">
              <Building2 className="h-3.5 w-3.5" />
              <span>{tenant?.subdomain}</span>
            </div>
          </div>
        </header>

        {/* Content Wrapper */}
        <main className="flex-1 overflow-y-auto p-6 bg-slate-950 bg-[radial-gradient(ellipse_60%_60%_at_50%_120%,rgba(74,111,165,0.08),rgba(255,255,255,0))]">
          {activeItem.view}
        </main>
      </div>

      {/* Mobile Drawer Navigation Menu */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden bg-slate-950/80 backdrop-blur-sm">
          <div className="relative flex flex-col w-80 max-w-xs bg-slate-950 border-r border-slate-900">
            <div className="h-16 flex items-center justify-between px-6 border-b border-slate-900">
              <span className="font-bold text-white select-none">Menu Navegação</span>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="p-1 rounded-lg border border-slate-800 text-slate-400 hover:text-slate-200 cursor-pointer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <nav className="flex-1 px-4 py-6 space-y-1">
              {navItems.map((item) => {
                const isActive = location.pathname === item.path
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    onClick={() => setMobileMenuOpen(false)}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                      isActive
                        ? 'bg-brand-500/10 text-brand-400 border-l-2 border-brand-500 font-medium'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/40'
                    }`}
                  >
                    <item.icon className="h-4.5 w-4.5 shrink-0" />
                    <span>{item.name}</span>
                  </Link>
                )
              })}
            </nav>

            <div className="p-4 border-t border-slate-900 space-y-3">
              <div className="flex items-center gap-3 px-2">
                <div className="h-9 w-9 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400 font-bold font-mono select-none">
                  VS
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-white truncate">{user?.name}</p>
                  <p className="text-[10px] text-slate-500 truncate">{user?.email}</p>
                </div>
              </div>
              <button
                onClick={() => {
                  setMobileMenuOpen(false)
                  handleLogout()
                }}
                className="w-full flex items-center justify-center gap-2 py-1.5 px-3 bg-red-950/20 hover:bg-red-950/40 border border-red-900/20 hover:border-red-900/40 text-red-400 text-xs rounded-lg transition-colors font-medium cursor-pointer"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span>Sair da conta</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <DashboardLayout />
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
