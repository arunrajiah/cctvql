import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Image, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CctvEvent } from '../types';

interface Props {
  event: CctvEvent;
  onPress: () => void;
}

export default function EventCard({ event, onPress }: Props) {
  const primaryLabel = event.objects[0]?.label ?? event.type;
  const confidence = event.objects[0]?.confidence;
  const time = new Date(event.start_time).toLocaleString([], {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });

  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.75}>
      {event.snapshot_url ? (
        <Image source={{ uri: event.snapshot_url }} style={styles.thumb} resizeMode="cover" />
      ) : (
        <View style={[styles.thumb, styles.thumbPlaceholder]}>
          <Ionicons name="camera-outline" size={22} color="#475569" />
        </View>
      )}
      <View style={styles.body}>
        <Text style={styles.camera} numberOfLines={1}>{event.camera}</Text>
        <View style={styles.labelRow}>
          <Text style={styles.label}>{primaryLabel}</Text>
          {confidence !== undefined && (
            <Text style={styles.conf}>{Math.round(confidence * 100)}%</Text>
          )}
        </View>
        {event.zones.length > 0 && (
          <Text style={styles.zone} numberOfLines={1}>{event.zones.join(', ')}</Text>
        )}
        <Text style={styles.time}>{time}</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color="#475569" style={styles.chevron} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    backgroundColor: '#1e293b',
    borderRadius: 12,
    marginBottom: 10,
    overflow: 'hidden',
  },
  thumb: { width: 80, height: 80 },
  thumbPlaceholder: { backgroundColor: '#0f172a', alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, padding: 10, justifyContent: 'center' },
  camera: { color: '#f8fafc', fontSize: 14, fontWeight: '600', marginBottom: 2 },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  label: { color: '#3b82f6', fontSize: 13, fontWeight: '500', textTransform: 'capitalize' },
  conf: { color: '#64748b', fontSize: 12 },
  zone: { color: '#64748b', fontSize: 12, marginTop: 2 },
  time: { color: '#475569', fontSize: 11, marginTop: 4 },
  chevron: { alignSelf: 'center', marginRight: 10 },
});
