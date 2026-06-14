import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useAuthStore } from '../store/authStore';
import { login } from '../api/auth';
import { fetchHealth } from '../api/auth';

export default function LoginScreen() {
  const { serverUrl, setServerUrl, setApiKey, loginWithJwt } = useAuthStore();
  const [url, setUrl] = useState(serverUrl);
  const [mode, setMode] = useState<'apikey' | 'password'>('apikey');
  const [apiKey, setApiKeyInput] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleConnect = async () => {
    if (!url.trim()) {
      Alert.alert('Error', 'Please enter the cctvQL server URL.');
      return;
    }
    setLoading(true);
    try {
      await setServerUrl(url.trim());

      if (mode === 'apikey') {
        // Verify health first
        await fetchHealth();
        await setApiKey(apiKey.trim());
      } else {
        const resp = await login({ username, password });
        await loginWithJwt(resp.access_token, username);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Could not connect to server.';
      Alert.alert('Connection failed', msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.logo}>cctvQL</Text>
        <Text style={styles.subtitle}>Ask your cameras anything</Text>

        <View style={styles.card}>
          <Text style={styles.label}>Server URL</Text>
          <TextInput
            style={styles.input}
            value={url}
            onChangeText={setUrl}
            placeholder="http://192.168.1.x:8000"
            placeholderTextColor="#64748b"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />

          <View style={styles.tabs}>
            <TouchableOpacity
              style={[styles.tab, mode === 'apikey' && styles.tabActive]}
              onPress={() => setMode('apikey')}
            >
              <Text style={[styles.tabText, mode === 'apikey' && styles.tabTextActive]}>
                API Key
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tab, mode === 'password' && styles.tabActive]}
              onPress={() => setMode('password')}
            >
              <Text style={[styles.tabText, mode === 'password' && styles.tabTextActive]}>
                Username / Password
              </Text>
            </TouchableOpacity>
          </View>

          {mode === 'apikey' ? (
            <>
              <Text style={styles.label}>API Key</Text>
              <TextInput
                style={styles.input}
                value={apiKey}
                onChangeText={setApiKeyInput}
                placeholder="Leave blank if no key is set"
                placeholderTextColor="#64748b"
                secureTextEntry
              />
            </>
          ) : (
            <>
              <Text style={styles.label}>Username</Text>
              <TextInput
                style={styles.input}
                value={username}
                onChangeText={setUsername}
                placeholder="admin"
                placeholderTextColor="#64748b"
                autoCapitalize="none"
              />
              <Text style={styles.label}>Password</Text>
              <TextInput
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                placeholder="••••••••"
                placeholderTextColor="#64748b"
                secureTextEntry
              />
            </>
          )}

          <TouchableOpacity style={styles.button} onPress={handleConnect} disabled={loading}>
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.buttonText}>Connect</Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  container: { flexGrow: 1, justifyContent: 'center', padding: 24 },
  logo: { color: '#f8fafc', fontSize: 36, fontWeight: '700', textAlign: 'center', marginBottom: 4 },
  subtitle: { color: '#94a3b8', fontSize: 15, textAlign: 'center', marginBottom: 32 },
  card: { backgroundColor: '#1e293b', borderRadius: 16, padding: 20 },
  label: { color: '#94a3b8', fontSize: 13, marginBottom: 6, marginTop: 14 },
  input: {
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    borderRadius: 10,
    padding: 12,
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  tabs: { flexDirection: 'row', marginTop: 20, marginBottom: 4, borderRadius: 8, overflow: 'hidden', backgroundColor: '#0f172a' },
  tab: { flex: 1, paddingVertical: 8, alignItems: 'center' },
  tabActive: { backgroundColor: '#3b82f6' },
  tabText: { color: '#64748b', fontSize: 13 },
  tabTextActive: { color: '#fff', fontWeight: '600' },
  button: { backgroundColor: '#3b82f6', borderRadius: 10, padding: 14, marginTop: 24, alignItems: 'center' },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
