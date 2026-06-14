import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import React, { useState } from 'react';
import {
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAuthStore } from '../store/authStore';
import { RootStackParamList } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function SettingsScreen() {
  const nav = useNavigation<Nav>();
  const { serverUrl, apiKey, username, isMultiTenant, setServerUrl, setApiKey, logout } =
    useAuthStore();

  const [urlInput, setUrlInput] = useState(serverUrl);
  const [keyInput, setKeyInput] = useState(apiKey);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    await setServerUrl(urlInput.trim());
    if (!isMultiTenant) await setApiKey(keyInput.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleLogout = () => {
    Alert.alert('Log out', 'Disconnect from this cctvQL server?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log out', style: 'destructive', onPress: logout },
    ]);
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      <Text style={styles.heading}>Settings</Text>

      {/* Connection */}
      <Section title="Connection">
        <Field label="Server URL">
          <TextInput
            style={styles.input}
            value={urlInput}
            onChangeText={setUrlInput}
            placeholder="http://192.168.1.x:8000"
            placeholderTextColor="#64748b"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
        </Field>
        {!isMultiTenant && (
          <Field label="API Key">
            <TextInput
              style={styles.input}
              value={keyInput}
              onChangeText={setKeyInput}
              placeholder="Optional"
              placeholderTextColor="#64748b"
              secureTextEntry
            />
          </Field>
        )}
        <TouchableOpacity style={[styles.button, saved && styles.buttonSaved]} onPress={save}>
          <Text style={styles.buttonText}>{saved ? '✓ Saved' : 'Save'}</Text>
        </TouchableOpacity>
      </Section>

      {/* Account */}
      {isMultiTenant && (
        <Section title="Account">
          <Row icon="person-outline" label="Logged in as" value={username} />
        </Section>
      )}

      {/* Face Recognition */}
      <Section title="Face Recognition">
        <TouchableOpacity style={styles.navRow} onPress={() => nav.navigate('FaceList')}>
          <Ionicons name="people-outline" size={20} color="#3b82f6" />
          <Text style={styles.navRowText}>Manage enrolled faces</Text>
          <Ionicons name="chevron-forward" size={16} color="#475569" />
        </TouchableOpacity>
      </Section>

      {/* About */}
      <Section title="About">
        <Row icon="information-circle-outline" label="App version" value={Constants.expoConfig?.version ?? '—'} />
        <Row icon="server-outline" label="Server" value={serverUrl} />
      </Section>

      {/* Logout */}
      <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
        <Ionicons name="log-out-outline" size={18} color="#ef4444" />
        <Text style={styles.logoutText}>Disconnect</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

function Row({ icon, label, value }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Ionicons name={icon} size={18} color="#64748b" />
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  container: { padding: 20, paddingTop: 60, paddingBottom: 40 },
  heading: { color: '#f8fafc', fontSize: 26, fontWeight: '700', marginBottom: 24 },
  section: { marginBottom: 24 },
  sectionTitle: { color: '#64748b', fontSize: 12, fontWeight: '600', textTransform: 'uppercase', marginBottom: 8, paddingHorizontal: 4 },
  sectionBody: { backgroundColor: '#1e293b', borderRadius: 14, padding: 16 },
  fieldLabel: { color: '#94a3b8', fontSize: 13, marginBottom: 6 },
  input: { backgroundColor: '#0f172a', color: '#f8fafc', borderRadius: 10, padding: 11, fontSize: 14, borderWidth: 1, borderColor: '#334155' },
  button: { backgroundColor: '#3b82f6', borderRadius: 10, padding: 12, alignItems: 'center', marginTop: 8 },
  buttonSaved: { backgroundColor: '#22c55e' },
  buttonText: { color: '#fff', fontWeight: '600' },
  navRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 2 },
  navRowText: { flex: 1, color: '#f8fafc', fontSize: 15 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: '#0f172a' },
  rowLabel: { flex: 1, color: '#94a3b8', fontSize: 14 },
  rowValue: { color: '#f8fafc', fontSize: 14, maxWidth: '50%' },
  logoutBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: '#1e293b', borderRadius: 12, padding: 14, marginTop: 8 },
  logoutText: { color: '#ef4444', fontSize: 15, fontWeight: '600' },
});
