// ─── Camera ──────────────────────────────────────────────────────────────────

export interface Camera {
  id: string;
  name: string;
  adapter: string;
  zones: string[];
  has_ptz: boolean;
  snapshot_url?: string;
  stream_url?: string;
}

export interface CameraHealth {
  camera_name: string;
  status: 'online' | 'offline' | 'unknown';
  last_seen?: string;
  latency_ms?: number;
}

export interface PTZPreset {
  id: string;
  name: string;
}

// ─── Events ──────────────────────────────────────────────────────────────────

export interface DetectedObject {
  label: string;
  confidence: number;
}

export interface CctvEvent {
  id: string;
  camera: string;
  type: string;
  start_time: string;
  end_time?: string;
  objects: DetectedObject[];
  zones: string[];
  snapshot_url?: string;
  clip_url?: string;
}

// ─── Anomaly ─────────────────────────────────────────────────────────────────

export interface Anomaly {
  camera: string;
  hour: string;
  observed: number;
  expected: number;
  z_score: number;
  severity: 'low' | 'medium' | 'high';
  type: 'spike' | 'silence';
}

// ─── Alert ───────────────────────────────────────────────────────────────────

export interface AlertRule {
  id: string;
  name: string;
  camera?: string;
  label?: string;
  zone?: string;
  time_start?: string;
  time_end?: string;
  enabled: boolean;
  created_at: string;
}

// ─── Query ───────────────────────────────────────────────────────────────────

export interface QueryResponse {
  answer: string;
  session_id: string;
  intent?: string;
  events?: CctvEvent[];
  cameras?: Camera[];
}

// ─── Face recognition ────────────────────────────────────────────────────────

export interface FaceEnrollment {
  face_id: string;
  name: string;
  label: string;
  created_at: string;
  image_b64: string;
}

export interface FaceMatch {
  face_id: string;
  name: string;
  label: string;
  confidence: number;
}

export interface RecognizeResult {
  face_count: number;
  recognition_available: boolean;
  matches: FaceMatch[];
}

// ─── Auth ────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  role: string;
}

// ─── Push tokens ─────────────────────────────────────────────────────────────

export interface PushRegisterRequest {
  token: string;
  platform: 'ios' | 'android';
  device_name: string;
}

// ─── Health ──────────────────────────────────────────────────────────────────

export interface HealthStatus {
  adapter: string;
  adapter_ok: boolean;
  llm: string;
  llm_ok: boolean;
}

// ─── Navigation param lists ──────────────────────────────────────────────────

export type AuthStackParamList = {
  Login: undefined;
};

export type MainTabParamList = {
  HomeTab: undefined;
  EventsTab: undefined;
  ChatTab: undefined;
  CamerasTab: undefined;
  SettingsTab: undefined;
};

export type RootStackParamList = {
  Auth: undefined;
  Main: undefined;
  EventDetail: { event: CctvEvent };
  CameraDetail: { camera: Camera };
  FaceList: undefined;
  FaceEnroll: undefined;
};
