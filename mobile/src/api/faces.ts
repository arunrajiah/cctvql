import { FaceEnrollment, RecognizeResult } from '../types';
import * as api from './client';

export const fetchFaces = (): Promise<FaceEnrollment[]> => api.get('/faces');

export const getFace = (faceId: string): Promise<FaceEnrollment> =>
  api.get(`/faces/${encodeURIComponent(faceId)}`);

export const deleteFace = (faceId: string): Promise<void> =>
  api.del(`/faces/${encodeURIComponent(faceId)}`);

/**
 * Enrol a new face.
 * @param name       Person's full name
 * @param label      Optional role / label
 * @param imageUri   Local file URI from the camera / image picker
 */
export const enrollFace = async (
  name: string,
  label: string,
  imageUri: string,
): Promise<FaceEnrollment> => {
  const form = new FormData();
  form.append('name', name);
  form.append('label', label);
  // React Native FormData accepts { uri, name, type } objects
  form.append('image', {
    uri: imageUri,
    name: 'face.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);
  return api.postForm<FaceEnrollment>('/faces/enroll', form);
};

/**
 * Recognise faces in a local image.
 */
export const recognizeFaces = async (
  imageUri: string,
  tolerance = 0.6,
): Promise<RecognizeResult> => {
  const form = new FormData();
  form.append('tolerance', String(tolerance));
  form.append('image', {
    uri: imageUri,
    name: 'query.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);
  return api.postForm<RecognizeResult>('/faces/recognize', form);
};

export const recognizeFromEvent = (
  eventId: string,
  tolerance = 0.6,
): Promise<RecognizeResult> =>
  api.get(`/faces/search/${encodeURIComponent(eventId)}`, { tolerance });
