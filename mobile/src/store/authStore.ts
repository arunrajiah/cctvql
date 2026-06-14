/**
 * Auth + settings store
 * ─────────────────────
 * Persists server URL, API key, JWT token, and session ID
 * to Expo SecureStore so credentials survive app restarts.
 */
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';
import { configureClient } from '../api/client';

const KEYS = {
  SERVER_URL: 'cctvql_server_url',
  API_KEY: 'cctvql_api_key',
  JWT_TOKEN: 'cctvql_jwt_token',
  USERNAME: 'cctvql_username',
  MULTI_TENANT: 'cctvql_multi_tenant',
} as const;

export interface AuthState {
  serverUrl: string;
  apiKey: string;
  jwtToken: string;
  username: string;
  isMultiTenant: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;

  // Actions
  setServerUrl: (url: string) => Promise<void>;
  setApiKey: (key: string) => Promise<void>;
  loginWithJwt: (token: string, username: string) => Promise<void>;
  logout: () => Promise<void>;
  hydrate: () => Promise<void>;
  _apply: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  serverUrl: 'http://localhost:8000',
  apiKey: '',
  jwtToken: '',
  username: '',
  isMultiTenant: false,
  isAuthenticated: false,
  isLoading: true,

  _apply: () => {
    const { serverUrl, apiKey, jwtToken } = get();
    configureClient({
      baseURL: serverUrl,
      apiKey: apiKey || undefined,
      jwtToken: jwtToken || undefined,
    });
  },

  setServerUrl: async (url: string) => {
    await SecureStore.setItemAsync(KEYS.SERVER_URL, url);
    set({ serverUrl: url });
    get()._apply();
  },

  setApiKey: async (key: string) => {
    await SecureStore.setItemAsync(KEYS.API_KEY, key);
    set({ apiKey: key, isAuthenticated: key.length > 0 });
    get()._apply();
  },

  loginWithJwt: async (token: string, username: string) => {
    await SecureStore.setItemAsync(KEYS.JWT_TOKEN, token);
    await SecureStore.setItemAsync(KEYS.USERNAME, username);
    await SecureStore.setItemAsync(KEYS.MULTI_TENANT, '1');
    set({ jwtToken: token, username, isMultiTenant: true, isAuthenticated: true });
    get()._apply();
  },

  logout: async () => {
    await SecureStore.deleteItemAsync(KEYS.JWT_TOKEN);
    await SecureStore.deleteItemAsync(KEYS.USERNAME);
    await SecureStore.deleteItemAsync(KEYS.MULTI_TENANT);
    set({ jwtToken: '', username: '', isMultiTenant: false, isAuthenticated: false });
    get()._apply();
  },

  hydrate: async () => {
    const serverUrl =
      (await SecureStore.getItemAsync(KEYS.SERVER_URL)) ?? 'http://localhost:8000';
    const apiKey = (await SecureStore.getItemAsync(KEYS.API_KEY)) ?? '';
    const jwtToken = (await SecureStore.getItemAsync(KEYS.JWT_TOKEN)) ?? '';
    const username = (await SecureStore.getItemAsync(KEYS.USERNAME)) ?? '';
    const isMultiTenant = (await SecureStore.getItemAsync(KEYS.MULTI_TENANT)) === '1';

    const isAuthenticated = jwtToken.length > 0 || apiKey.length > 0;
    set({ serverUrl, apiKey, jwtToken, username, isMultiTenant, isAuthenticated, isLoading: false });
    configureClient({
      baseURL: serverUrl,
      apiKey: apiKey || undefined,
      jwtToken: jwtToken || undefined,
    });
  },
}));
