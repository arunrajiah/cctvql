import { QueryResponse } from '../types';
import * as api from './client';

export const sendQuery = (
  query: string,
  sessionId?: string,
  multi?: boolean,
): Promise<QueryResponse> =>
  api.post('/query', { query, session_id: sessionId, multi: multi ?? false });

export const clearSession = (sessionId: string): Promise<void> =>
  api.del(`/sessions/${encodeURIComponent(sessionId)}`);
