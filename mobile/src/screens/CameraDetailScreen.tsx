import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useState } from 'react';
import { Alert, Image, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { fetchPTZPresets, sendPTZCommand } from '../api/cameras';
import PTZJoystick from '../components/PTZJoystick';
import { RootStackParamList } from '../types';

type Props = NativeStackScreenProps<RootStackParamList, 'CameraDetail'>;

export default function CameraDetailScreen({ route }: Props) {
  const { camera } = route.params;
  const [ptzLoading, setPtzLoading] = useState(false);

  const presetsQuery = useQuery({
    queryKey: ['ptzPresets', camera.id],
    queryFn: () => fetchPTZPresets(camera.id),
    enabled: camera.has_ptz,
  });

  const ptzCommand = async (
    action: Parameters<typeof sendPTZCommand>[1],
    opts?: Parameters<typeof sendPTZCommand>[2],
  ) => {
    setPtzLoading(true);
    try {
      await sendPTZCommand(camera.id, action, opts);
    } catch {
      Alert.alert('PTZ Error', 'Command failed. Check camera connection.');
    } finally {
      setPtzLoading(false);
    }
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      {/* Live snapshot */}
      {camera.snapshot_url ? (
        <Image source={{ uri: camera.snapshot_url }} style={styles.snapshot} resizeMode="cover" />
      ) : (
        <View style={styles.noSnap}>
          <Ionicons name="videocam-off-outline" size={40} color="#475569" />
          <Text style={styles.noSnapText}>No snapshot URL</Text>
        </View>
      )}

      {/* Info */}
      <View style={styles.card}>
        <Row label="Name" value={camera.name} />
        <Row label="Adapter" value={camera.adapter} />
        <Row label="Zones" value={camera.zones.join(', ') || 'None'} />
        <Row label="PTZ" value={camera.has_ptz ? 'Supported' : 'Not supported'} />
      </View>

      {/* PTZ controls */}
      {camera.has_ptz && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>PTZ Control</Text>
          <PTZJoystick onCommand={ptzCommand} loading={ptzLoading} />

          {/* Presets */}
          {presetsQuery.data && presetsQuery.data.length > 0 && (
            <>
              <Text style={[styles.cardTitle, { marginTop: 16 }]}>Presets</Text>
              <View style={styles.presetRow}>
                {presetsQuery.data.map((preset) => (
                  <TouchableOpacity
                    key={preset.id}
                    style={styles.presetChip}
                    onPress={() => ptzCommand('preset', { preset_id: preset.id })}
                  >
                    <Text style={styles.presetText}>{preset.name}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </>
          )}
        </View>
      )}
    </ScrollView>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  container: { paddingBottom: 40 },
  snapshot: { width: '100%', height: 220, backgroundColor: '#1e293b' },
  noSnap: { height: 160, backgroundColor: '#1e293b', alignItems: 'center', justifyContent: 'center', gap: 8 },
  noSnapText: { color: '#475569' },
  card: { margin: 16, backgroundColor: '#1e293b', borderRadius: 14, padding: 16, marginBottom: 0 },
  cardTitle: { color: '#94a3b8', fontSize: 12, fontWeight: '600', textTransform: 'uppercase', marginBottom: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#0f172a' },
  rowLabel: { color: '#64748b', fontSize: 14 },
  rowValue: { color: '#f8fafc', fontSize: 14, flex: 1, textAlign: 'right' },
  presetRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  presetChip: { backgroundColor: '#0f172a', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: '#334155' },
  presetText: { color: '#f8fafc', fontSize: 13 },
});
