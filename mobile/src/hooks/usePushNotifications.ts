/**
 * usePushNotifications
 * ─────────────────────
 * Requests notification permission, retrieves the Expo push token,
 * and registers it with the cctvQL backend.
 *
 * Call once from App.tsx after the user is authenticated.
 */
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useEffect, useRef } from 'react';
import { Platform } from 'react-native';
import { registerPushToken } from '../api/push';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

export function usePushNotifications(enabled: boolean) {
  const registered = useRef(false);

  useEffect(() => {
    if (!enabled || registered.current) return;
    registerForPushNotificationsAsync()
      .then((token) => {
        if (!token) return;
        return registerPushToken({
          token,
          platform: Platform.OS as 'ios' | 'android',
          device_name: Device.deviceName ?? Device.modelName ?? 'Unknown',
        });
      })
      .then(() => {
        registered.current = true;
      })
      .catch((err) => {
        console.warn('[Push] registration failed:', err);
      });
  }, [enabled]);
}

async function registerForPushNotificationsAsync(): Promise<string | null> {
  if (!Device.isDevice) {
    console.warn('[Push] Push notifications only work on physical devices.');
    return null;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    console.warn('[Push] Permission not granted for push notifications.');
    return null;
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('cctvql-alerts', {
      name: 'cctvQL Alerts',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#FF231F7C',
    });
  }

  const tokenData = await Notifications.getExpoPushTokenAsync();
  return tokenData.data;
}
