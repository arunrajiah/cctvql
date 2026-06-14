import { Ionicons } from '@expo/vector-icons';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import React from 'react';

import { useAuthStore } from '../store/authStore';
import { AuthStackParamList, MainTabParamList, RootStackParamList } from '../types';

// Screens
import LoginScreen from '../screens/LoginScreen';
import HomeScreen from '../screens/HomeScreen';
import EventsScreen from '../screens/EventsScreen';
import EventDetailScreen from '../screens/EventDetailScreen';
import ChatScreen from '../screens/ChatScreen';
import CameraListScreen from '../screens/CameraListScreen';
import CameraDetailScreen from '../screens/CameraDetailScreen';
import FaceListScreen from '../screens/FaceListScreen';
import FaceEnrollScreen from '../screens/FaceEnrollScreen';
import SettingsScreen from '../screens/SettingsScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();
const AuthStack = createNativeStackNavigator<AuthStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

const ICON_MAP: Record<string, { focused: string; outline: string }> = {
  HomeTab:     { focused: 'home',          outline: 'home-outline' },
  EventsTab:   { focused: 'list',          outline: 'list-outline' },
  ChatTab:     { focused: 'chatbubbles',   outline: 'chatbubbles-outline' },
  CamerasTab:  { focused: 'videocam',      outline: 'videocam-outline' },
  SettingsTab: { focused: 'settings',      outline: 'settings-outline' },
};

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: '#3b82f6',
        tabBarInactiveTintColor: '#94a3b8',
        tabBarStyle: { backgroundColor: '#0f172a', borderTopColor: '#1e293b' },
        tabBarIcon: ({ focused, color, size }) => {
          const icons = ICON_MAP[route.name];
          const name = (focused ? icons.focused : icons.outline) as React.ComponentProps<
            typeof Ionicons
          >['name'];
          return <Ionicons name={name} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="HomeTab"    component={HomeScreen}       options={{ title: 'Home' }} />
      <Tab.Screen name="EventsTab"  component={EventsScreen}     options={{ title: 'Events' }} />
      <Tab.Screen name="ChatTab"    component={ChatScreen}       options={{ title: 'Ask' }} />
      <Tab.Screen name="CamerasTab" component={CameraListScreen} options={{ title: 'Cameras' }} />
      <Tab.Screen name="SettingsTab" component={SettingsScreen}  options={{ title: 'Settings' }} />
    </Tab.Navigator>
  );
}

function AuthNavigator() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="Login" component={LoginScreen} />
    </AuthStack.Navigator>
  );
}

export default function AppNavigator() {
  const { isAuthenticated } = useAuthStore();

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {isAuthenticated ? (
          <>
            <Stack.Screen name="Main" component={MainTabs} />
            <Stack.Screen
              name="EventDetail"
              component={EventDetailScreen}
              options={{ headerShown: true, title: 'Event Detail', headerStyle: { backgroundColor: '#0f172a' }, headerTintColor: '#f8fafc' }}
            />
            <Stack.Screen
              name="CameraDetail"
              component={CameraDetailScreen}
              options={{ headerShown: true, title: 'Camera', headerStyle: { backgroundColor: '#0f172a' }, headerTintColor: '#f8fafc' }}
            />
            <Stack.Screen
              name="FaceList"
              component={FaceListScreen}
              options={{ headerShown: true, title: 'Enrolled Faces', headerStyle: { backgroundColor: '#0f172a' }, headerTintColor: '#f8fafc' }}
            />
            <Stack.Screen
              name="FaceEnroll"
              component={FaceEnrollScreen}
              options={{ headerShown: true, title: 'Enrol Face', headerStyle: { backgroundColor: '#0f172a' }, headerTintColor: '#f8fafc' }}
            />
          </>
        ) : (
          <Stack.Screen name="Auth" component={AuthNavigator} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
