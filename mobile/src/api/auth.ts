import { HealthStatus, LoginRequest, LoginResponse } from '../types';
import * as api from './client';

export const login = (body: LoginRequest): Promise<LoginResponse> =>
  api.post('/auth/login', body);

export const fetchHealth = (): Promise<HealthStatus> => api.get('/health');
