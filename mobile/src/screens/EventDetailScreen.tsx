import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React from 'react';
import { Image, Linking, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { recognizeFromEvent } from '../api/faces';
import { RootStackParamList } from '../types';

type Props = NativeStackScreenProps<RootStackParamList, 'EventDetail'>;

export default function EventDetailScreen({ route }: Props) {
  const { event } = route.params;

  const faceQuery = useQuery({
    queryKey: ['faceSearch', event.id],
    queryFn: () => recognizeFromEvent(event.id),
    enabled: !!event.snapshot_url,
    retry: false,
  });

  const startTime = new Date(event.start_time).toLocaleString();
  const endTime = event.end_time ? new Date(event.end_time).toLocaleString() : '—';

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.container}>
      {/* Snapshot */}
      {event.snapshot_url ? (
        <Image source={{ uri: event.snapshot_url }} style={styles.snapshot} resizeMode="cover" />
      ) : (
        <View style={styles.noSnapshot}>
          <Ionicons name="image-outline" size={48} color="#475569" />
          <Text style={styles.noSnapshotText}>No snapshot available</Text>
        </View>
      )}

      {/* Meta */}
      <View style={styles.card}>
        <Row label="Camera" value={event.camera} />
        <Row label="Type" value={event.type} />
        <Row label="Started" value={startTime} />
        <Row label="Ended" value={endTime} />
        {event.zones.length > 0 && <Row label="Zones" value={event.zones.join(', ')} />}
      </View>

      {/* Objects */}
      {event.objects.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Detected objects</Text>
          {event.objects.map((obj, i) => (
            <View key={i} style={styles.objRow}>
              <Text style={styles.objLabel}>{obj.label}</Text>
              <View style={[styles.confBar, { width: `${Math.round(obj.confidence * 100)}%` }]} />
              <Text style={styles.confText}>{Math.round(obj.confidence * 100)}%</Text>
            </View>
          ))}
        </View>
      )}

      {/* Face recognition */}
      {event.snapshot_url && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Face recognition</Text>
          {faceQuery.isLoading && <Text style={styles.muted}>Analysing…</Text>}
          {faceQuery.data && !faceQuery.data.recognition_available && (
            <Text style={styles.muted}>face_recognition library not installed on server.</Text>
          )}
          {faceQuery.data?.recognition_available && faceQuery.data.matches.length === 0 && (
            <Text style={styles.muted}>
              {faceQuery.data.face_count} face(s) detected — no enrolled match found.
            </Text>
          )}
          {faceQuery.data?.matches.map((m) => (
            <View key={m.face_id} style={styles.matchRow}>
              <Ionicons name="person-circle-outline" size={28} color="#3b82f6" />
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.matchName}>{m.name}</Text>
                {m.label ? <Text style={styles.matchLabel}>{m.label}</Text> : null}
              </View>
              <Text style={styles.confText}>{Math.round(m.confidence * 100)}%</Text>
            </View>
          ))}
        </View>
      )}

      {/* Clip link */}
      {event.clip_url && (
        <TouchableOpacity style={styles.button} onPress={() => Linking.openURL(event.clip_url!)}>
          <Ionicons name="play-circle-outline" size={20} color="#fff" />
          <Text style={styles.buttonText}>Open clip</Text>
        </TouchableOpacity>
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
  noSnapshot: { height: 180, backgroundColor: '#1e293b', alignItems: 'center', justifyContent: 'center', gap: 8 },
  noSnapshotText: { color: '#475569' },
  card: { margin: 16, backgroundColor: '#1e293b', borderRadius: 14, padding: 16, marginBottom: 0 },
  cardTitle: { color: '#94a3b8', fontSize: 12, fontWeight: '600', textTransform: 'uppercase', marginBottom: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: '#0f172a' },
  rowLabel: { color: '#64748b', fontSize: 14 },
  rowValue: { color: '#f8fafc', fontSize: 14, flex: 1, textAlign: 'right' },
  objRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 },
  objLabel: { color: '#f8fafc', width: 80, fontSize: 14 },
  confBar: { height: 6, backgroundColor: '#3b82f6', borderRadius: 3, maxWidth: '60%' },
  confText: { color: '#64748b', fontSize: 12, marginLeft: 'auto' },
  matchRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#0f172a' },
  matchName: { color: '#f8fafc', fontSize: 15, fontWeight: '600' },
  matchLabel: { color: '#64748b', fontSize: 12 },
  muted: { color: '#475569', fontSize: 14 },
  button: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, margin: 16, backgroundColor: '#3b82f6', borderRadius: 12, padding: 14 },
  buttonText: { color: '#fff', fontWeight: '600', fontSize: 15 },
});
