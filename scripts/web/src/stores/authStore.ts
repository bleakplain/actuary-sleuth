import { create } from 'zustand';
import client from '../api/client';

interface AuthState {
  token: string | null;
  user: { id: string; email: string; role_id: string; display_name: string } | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loadUser: () => Promise<void>;
}

const TOKEN_KEY = 'auth_token';

function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: getStoredToken(),
  user: null,

  login: async (email: string, password: string) => {
    const res = await client.post('/api/auth/login', { email, password });
    const { access_token } = res.data;
    localStorage.setItem(TOKEN_KEY, access_token);
    client.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
    set({ token: access_token });
    await get().loadUser();
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    delete client.defaults.headers.common['Authorization'];
    set({ token: null, user: null });
  },

  loadUser: async () => {
    try {
      const res = await client.get('/api/auth/me');
      set({ user: res.data });
    } catch {
      get().logout();
    }
  },
}));

// Initialize token on load
const token = getStoredToken();
if (token) {
  client.defaults.headers.common['Authorization'] = `Bearer ${token}`;
}
