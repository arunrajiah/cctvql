import { Camera, CameraHealth, PTZPreset } from '../types';
import * as api from './client';

export const fetchCameras = (): Promise<Camera[]> => api.get('/cameras');

export const fetchCameraHealth = (): Promise<{ cameras: CameraHealth[] }> =>
  api.get('/health/cameras');

export const fetchPTZPresets = (cameraId: string): Promise<PTZPreset[]> =>
  api.get(`/cameras/${encodeURIComponent(cameraId)}/ptz/presets`);

export const sendPTZCommand = (
  cameraId: string,
  action: 'left' | 'right' | 'up' | 'down' | 'zoom_in' | 'zoom_out' | 'stop' | 'preset',
  opts?: { speed?: number; preset_id?: string },
): Promise<{ ok: boolean }> =>
  api.post(`/cameras/${encodeURIComponent(cameraId)}/ptz`, { action, ...opts });
