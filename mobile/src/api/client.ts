/**
 * cctvQL API client
 * -----------------
 * Thin axios wrapper that reads the server URL and auth credentials
 * from the Zustand auth store and applies them to every request.
 */
import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';

let _baseURL = 'http://localhost:8000';
let _apiKey: string | undefined;
let _jwtToken: string | undefined;

/** Called by the auth store after settings change. */
export function configureClient(opts: {
  baseURL: string;
  apiKey?: string;
  jwtToken?: string;
}) {
  _baseURL = opts.baseURL.replace(/\/$/, '');
  _apiKey = opts.apiKey;
  _jwtToken = opts.jwtToken;
}

function buildInstance(): AxiosInstance {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (_jwtToken) headers['Authorization'] = `Bearer ${_jwtToken}`;
  else if (_apiKey) headers['X-API-Key'] = _apiKey;

  return axios.create({ baseURL: _baseURL, timeout: 20_000, headers });
}

/** Execute a GET request. */
export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const r = await buildInstance().get<T>(path, { params });
  return r.data;
}

/** Execute a POST request (JSON body). */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await buildInstance().post<T>(path, body);
  return r.data;
}

/** Execute a POST request with a FormData body (multipart). */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const instance = buildInstance();
  const r = await instance.post<T>(path, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  } as AxiosRequestConfig);
  return r.data;
}

/** Execute a PATCH request. */
export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const r = await buildInstance().patch<T>(path, body);
  return r.data;
}

/** Execute a DELETE request. */
export async function del<T = void>(path: string): Promise<T> {
  const r = await buildInstance().delete<T>(path);
  return r.data;
}

/** Return the current base URL (used to build WebSocket URLs). */
export function getBaseURL(): string {
  return _baseURL;
}
