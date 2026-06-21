import { create } from 'zustand'
import { persist } from 'zustand/middleware'

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
  refreshToken: string | null;
  permissions: string[];
  isLoading: boolean;
  error: string | null;
  login: (
    tokens: { token: string; refreshToken: string },
    user: User,
    tenant: Tenant,
    permissions: string[],
  ) => void;
  logout: () => void;
  setTenant: (tenant: Tenant) => void;
  setError: (error: string | null) => void;
  setLoading: (isLoading: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      isAuthenticated: false,
      user: null,
      tenant: null,
      token: null,
      refreshToken: null,
      permissions: [],
      isLoading: false,
      error: null,

      login: (tokens, user, tenant, permissions) =>
        set({
          isAuthenticated: true,
          token: tokens.token,
          refreshToken: tokens.refreshToken,
          user,
          tenant,
          permissions,
          error: null,
        }),

      logout: () =>
        set({
          isAuthenticated: false,
          token: null,
          refreshToken: null,
          user: null,
          tenant: null,
          permissions: [],
          error: null,
        }),

      setTenant: (tenant) => set({ tenant }),
      setError: (error) => set({ error }),
      setLoading: (isLoading) => set({ isLoading }),
    }),
    {
      name: 'erp-v-auth',
      // Não persistir estado efêmero de UI.
      partialize: (state) => ({
        isAuthenticated: state.isAuthenticated,
        user: state.user,
        tenant: state.tenant,
        token: state.token,
        refreshToken: state.refreshToken,
        permissions: state.permissions,
      }),
    },
  ),
)
