import { PushRegisterRequest } from '../types';
import * as api from './client';

export const registerPushToken = (req: PushRegisterRequest): Promise<{ token: string }> =>
  api.post('/push/register', req);

export const unregisterPushToken = (token: string): Promise<void> =>
  api.del(`/push/register/${encodeURIComponent(token)}`);
