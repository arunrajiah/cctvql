import { CctvEvent } from '../types';
import * as api from './client';

export interface FetchEventsParams {
  camera?: string;
  label?: string;
  zone?: string;
  after?: number;
  before?: number;
  limit?: number;
}

export const fetchEvents = (params?: FetchEventsParams): Promise<CctvEvent[]> =>
  api.get('/events', params as Record<string, unknown>);

export const fetchTimeline = (params?: {
  hours?: number;
  bucket_minutes?: number;
  camera?: string;
}): Promise<{
  cameras: string[];
  buckets: string[];
  bucket_minutes: number;
  range_start: string;
  range_end: string;
  data: Record<string, Record<string, { count: number; top_label: string | null }>>;
}> => api.get('/events/timeline', params as Record<string, unknown>);

export const fetchAnomalies = (params?: {
  hours?: number;
  baseline_days?: number;
  camera?: string;
  threshold?: number;
}): Promise<{
  total: number;
  high: number;
  medium: number;
  low: number;
  anomalies: import('../types').Anomaly[];
}> => api.get('/anomalies', params as Record<string, unknown>);
