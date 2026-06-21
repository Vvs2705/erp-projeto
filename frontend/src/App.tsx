import React, { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { authApi, ApiError } from './lib/api'
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
  CheckCircle2,
  Clock,
  ShieldCheck
} from 'lucide-react'

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
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
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

// Mock Dashboard view
function DashboardView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Olá, Bem-vindo de Volta</h2>
        <p className="text-slate-400 text-sm">Resumo da saúde financeira e fiscal da sua organização.</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { title: 'Faturamento Bruto', value: 'R$ 142.384,90', icon: DollarSign, change: '+12.5%', isUp: true },
          { title: 'Notas Fiscais Emitidas', value: '843', icon: FileSpreadsheet, change: '+8.2%', isUp: true },
          { title: 'Impostos Retidos', value: 'R$ 28.490,11', icon: TrendingUp, change: '-2.1%', isUp: false },
          { title: 'Clientes Ativos', value: '1.240', icon: Users, change: '+4.3%', isUp: true }
        ].map((stat, idx) => (
          <div key={idx} className="glass-panel p-5 rounded-xl border border-slate-800 flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{stat.title}</span>
              <div className="p-2 rounded-lg bg-brand-950 border border-brand-900/50 text-brand-400">
                <stat.icon className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-4">
              <span className="text-2xl font-bold text-white">{stat.value}</span>
              <div className="flex items-center gap-1.5 mt-1">
                <span className={`text-xs font-semibold ${stat.isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {stat.change}
                </span>
                <span className="text-xs text-slate-500">vs. mês anterior</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts section mockup */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="glass-panel p-5 rounded-xl border border-slate-800 lg:col-span-2 flex flex-col justify-between">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-semibold text-white">Desempenho de Notas Fiscais</h3>
            <span className="text-xs text-brand-400 hover:underline cursor-pointer">Exportar relatório</span>
          </div>
          
          <div className="h-64 flex items-end gap-3 px-2 pt-4 border-b border-slate-800">
            {[55, 78, 45, 90, 120, 95, 110, 130, 85, 140, 160, 180].map((h, i) => (
              <div key={i} className="flex-1 flex flex-col items-center group cursor-pointer h-full justify-end">
                <div 
                  style={{ height: `${(h / 180) * 100}%` }} 
                  className="w-full bg-brand-500/30 hover:bg-brand-500 rounded-t transition-all relative"
                >
                  <div className="opacity-0 group-hover:opacity-100 absolute -top-8 left-1/2 transform -translate-x-1/2 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-[10px] text-white whitespace-nowrap shadow-xl z-10">
                    R$ {h}k
                  </div>
                </div>
                <span className="text-[10px] text-slate-500 mt-2 select-none">M{i+1}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Status system details */}
        <div className="glass-panel p-5 rounded-xl border border-slate-800 flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-white mb-4">Integração do Inquilino</h3>
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded bg-emerald-950 text-emerald-400">
                  <ShieldCheck className="h-4 w-4" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-white">Assinatura Ativa</h4>
                  <p className="text-[10px] text-slate-400">Plano Enterprise com suporte prioritário</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="p-2 rounded bg-brand-950 text-brand-400">
                  <CheckCircle2 className="h-4 w-4" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-white">Módulo Fiscal (SPED/Reinf)</h4>
                  <p className="text-[10px] text-slate-400">Sincronização com RFB em conformidade</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="p-2 rounded bg-amber-950 text-amber-400">
                  <Clock className="h-4 w-4" />
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-white">Último Backup Realizado</h4>
                  <p className="text-[10px] text-slate-400">Hoje às 04:00 AM (AWS S3)</p>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-900">
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-500">Mapeamento de Rotas API</span>
              <span className="font-mono text-slate-400 select-none">v1.2.4-stable</span>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Activity Table */}
      <div className="glass-panel rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-900 flex justify-between items-center">
          <h3 className="font-semibold text-white">Últimas NF-e Emitidas</h3>
          <button className="text-xs text-brand-400 hover:underline cursor-pointer">Ver todas</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-900/50 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-900">
                <th className="px-5 py-3">Número/Série</th>
                <th className="px-5 py-3">Destinatário</th>
                <th className="px-5 py-3">Valor Total</th>
                <th className="px-5 py-3">Data Emissão</th>
                <th className="px-5 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-900">
              {[
                { nfe: '000.129.432 / S1', client: 'Alpha Tech Ltda', value: 'R$ 15.420,00', date: 'Hoje às 10:15', status: 'Autorizada', color: 'text-emerald-400 bg-emerald-950/45 border-emerald-800/40' },
                { nfe: '000.129.431 / S1', client: 'Indústrias Premium SA', value: 'R$ 89.100,50', date: 'Ontem às 18:24', status: 'Autorizada', color: 'text-emerald-400 bg-emerald-950/45 border-emerald-800/40' },
                { nfe: '000.129.430 / S1', client: 'Vortex Serviços de TI', value: 'R$ 4.290,00', date: '14 de Junho', status: 'Rejeitada', color: 'text-rose-400 bg-rose-950/45 border-rose-800/40' },
                { nfe: '000.129.429 / S1', client: 'Mercado Confiança Ltda', value: 'R$ 1.250,00', date: '12 de Junho', status: 'Processando', color: 'text-amber-400 bg-amber-950/45 border-amber-800/40' },
              ].map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-900/35 transition-colors">
                  <td className="px-5 py-3.5 font-semibold text-white">{row.nfe}</td>
                  <td className="px-5 py-3.5 text-slate-300">{row.client}</td>
                  <td className="px-5 py-3.5 font-mono text-slate-300">{row.value}</td>
                  <td className="px-5 py-3.5 text-slate-400">{row.date}</td>
                  <td className="px-5 py-3.5">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-medium ${row.color}`}>
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// Invoices view skeleton
function InvoicesView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Notas Fiscais de Produto & Serviço</h2>
        <p className="text-slate-400 text-sm">Gerenciamento completo das NF-e, NFS-e e seus respectivos XMLs.</p>
      </div>

      <div className="glass-panel p-5 rounded-xl border border-slate-800 flex justify-between items-center">
        <div className="flex gap-3">
          <input 
            type="text" 
            placeholder="Pesquisar por número ou cliente..."
            className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:ring-1 focus:ring-brand-500 w-64"
          />
          <select className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none">
            <option>Todos os status</option>
            <option>Autorizada</option>
            <option>Processando</option>
            <option>Rejeitada</option>
          </select>
        </div>

        <button className="glow-btn bg-brand-500 text-white font-medium py-1.5 px-4 rounded-lg text-xs shadow-lg shadow-brand-500/20 hover:bg-brand-600 transition-all cursor-pointer">
          Nova NF-e
        </button>
      </div>

      <div className="glass-panel p-10 rounded-xl border border-slate-800 text-center">
        <FileSpreadsheet className="h-12 w-12 mx-auto text-slate-600 mb-4" />
        <h3 className="text-lg font-semibold text-white">Repositório Fiscal Integrado</h3>
        <p className="text-slate-400 text-sm mt-1 max-w-md mx-auto">
          Pronto para se comunicar com as SEFAZs estaduais e prefeituras municipais via motor fiscal dedicado.
        </p>
      </div>
    </div>
  )
}

// Clients view skeleton
function ClientsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Clientes Cadastrados</h2>
        <p className="text-slate-400 text-sm">Controle de clientes corporativos e individuais (CRM / ERP).</p>
      </div>

      <div className="glass-panel p-10 rounded-xl border border-slate-800 text-center">
        <Users className="h-12 w-12 mx-auto text-slate-600 mb-4" />
        <h3 className="text-lg font-semibold text-white">Gestão Unificada de Cadastros</h3>
        <p className="text-slate-400 text-sm mt-1 max-w-md mx-auto">
          Gerencie contatos, endereços fiscais, inscrições estaduais e regimes tributários.
        </p>
      </div>
    </div>
  )
}

// Settings view skeleton
function SettingsView() {
  const tenant = useAuthStore((state) => state.tenant)
  const user = useAuthStore((state) => state.user)

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
              <span className="text-slate-400 font-sans">Nome:</span>
              <span className="text-white font-medium">{user?.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">E-mail:</span>
              <span className="text-white font-mono">{user?.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400 font-sans">Permissão:</span>
              <span className="px-2 py-0.5 rounded bg-slate-900 text-slate-300 font-semibold border border-slate-800 uppercase text-[9px] select-none">
                {user?.role}
              </span>
            </div>
          </div>
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
