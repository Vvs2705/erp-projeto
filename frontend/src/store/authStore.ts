import { create } from 'zustand'

export interface User {
  id: string;
  name: string;
  email: string;
  role: 'admin' | 'gerente' | 'operador' | 'fiscal_admin';
}

export interface Tenant {
  id: string;
  name: string;
  subdomain: string;
  plan: 'basic' | 'pro' | 'enterprise';
}

interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  tenant: Tenant | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
  login: (token: string, user: User, tenant: Tenant) => void;
  logout: () => void;
  setTenant: (tenant: Tenant) => void;
  setError: (error: string | null) => void;
  setLoading: (isLoading: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  user: null,
  tenant: null,
  token: null,
  isLoading: false,
  error: null,

  login: (token, user, tenant) => set({
    isAuthenticated: true,
    token,
    user,
    tenant,
    error: null
  }),

  logout: () => set({
    isAuthenticated: false,
    token: null,
    user: null,
    tenant: null,
    error: null
  }),

  setTenant: (tenant) => set({ tenant }),
  setError: (error) => set({ error }),
  setLoading: (isLoading) => set({ isLoading }),
}))
