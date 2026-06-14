import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Camera } from '../types';

interface Props {
  camera: Camera;
  status: 'online' | 'offline' | 'unknown';
  onPress: () => void;
}

const STATUS_COLOR: Record<string, string> = {
  online: '#22c55e',
  offline: '#ef4444',
  unknown: '#f59e0b',
};

const STATUS_LABEL: Record<string, string> = {
  online: 'Online',
  offline: 'Offline',
  unknown: 'Unknown',
};

export default function CameraCard({ camera, status, onPress }: Props) {
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.75}>
      <View style={[styles.dot, { backgroundColor: STATUS_COLOR[status] ?? '#f59e0b' }]} />
      <View style={styles.body}>
        <Text style={styles.name} numberOfLines={1}>{camera.name}</Text>
        <Text style={styles.adapter}>{camera.adapter}</Text>
        {camera.zones.length > 0 && (
          <Text style={styles.zones} numberOfLines={1}>{camera.zones.join(' · ')}</Text>
        )}
      </View>
      <View style={styles.right}>
        <Text style={[styles.status, { color: STATUS_COLOR[status] }]}>
          {STATUS_LABEL[status]}
        </Text>
        {camera.has_ptz && (
          <Ionicons name="game-controller-outline" size={14} color="#475569" style={{ marginTop: 4 }} />
        )}
      </View>
      <Ionicons name="chevron-forward" size={16} color="#475569" />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1e293b',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    gap: 10,
  },
  dot: { width: 10, height: 10, borderRadius: 5 },
  body: { flex: 1 },
  name: { color: '#f8fafc', fontSize: 15, fontWeight: '600' },
  adapter: { color: '#64748b', fontSize: 12, marginTop: 2 },
  zones: { color: '#475569', fontSize: 11, marginTop: 2 },
  right: { alignItems: 'flex-end' },
  status: { fontSize: 12, fontWeight: '600' },
});
