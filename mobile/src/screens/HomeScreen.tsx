import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { fetchHealth } from '../api/auth';
import { fetchCameraHealth } from '../api/cameras';
import { fetchEvents } from '../api/events';
import { RootStackParamList } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function HomeScreen() {
  const nav = useNavigation<Nav>();

  const health = useQuery({ queryKey: ['health'], queryFn: fetchHealth, refetchInterval: 60_000 });
  const cams = useQuery({ queryKey: ['cameraHealth'], queryFn: fetchCameraHealth, refetchInterval: 60_000 });
  const events = useQuery({ queryKey: ['events', { limit: 5 }], queryFn: () => fetchEvents({ limit: 5 }) });

  const online = cams.data?.cameras.filter((c) => c.status === 'online').length ?? 0;
  const offline = cams.data?.cameras.filter((c) => c.status === 'offline').length ?? 0;
  const total = (cams.data?.cameras.length ?? 0);

  const refreshing = health.isFetching || cams.isFetching || events.isFetching;
  const refetch = () => { health.refetch(); cams.refetch(); events.refetch(); };

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refetch} tintColor="#3b82f6" />}
    >
      <Text style={styles.heading}>Dashboard</Text>

      {/* Status cards */}
      <View style={styles.row}>
        <StatCard
          icon="server-outline"
          label="Adapter"
          value={health.data?.adapter_ok ? 'Online' : 'Offline'}
          color={health.data?.adapter_ok ? '#22c55e' : '#ef4444'}
        />
        <StatCard
          icon="hardware-chip-outline"
          label="LLM"
          value={health.data?.llm_ok ? 'Online' : 'Offline'}
          color={health.data?.llm_ok ? '#22c55e' : '#ef4444'}
        />
      </View>
      <View style={styles.row}>
        <StatCard icon="videocam-outline" label="Cameras online" value={`${online} / ${total}`} color="#3b82f6" />
        <StatCard icon="warning-outline" label="Cameras offline" value={String(offline)} color={offline > 0 ? '#f59e0b' : '#22c55e'} />
      </View>

      {/* Recent events */}
      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Recent Events</Text>
          <TouchableOpacity onPress={() => nav.navigate('Main')}>
            <Text style={styles.seeAll}>See all →</Text>
          </TouchableOpacity>
        </View>
        {events.data?.slice(0, 5).map((evt) => (
          <TouchableOpacity
            key={evt.id}
            style={styles.eventRow}
            onPress={() => nav.navigate('EventDetail', { event: evt })}
          >
            <View style={styles.eventDot} />
            <View style={styles.eventInfo}>
              <Text style={styles.eventCamera}>{evt.camera}</Text>
              <Text style={styles.eventMeta}>
                {evt.objects[0]?.label ?? evt.type} · {new Date(evt.start_time).toLocaleTimeString()}
              </Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color="#475569" />
          </TouchableOpacity>
        ))}
        {!events.data?.length && (
          <Text style={styles.empty}>No recent events</Text>
        )}
      </View>
    </ScrollView>
  );
}

function StatCard({ icon, label, value, color }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; value: string; color: string }) {
  return (
    <View style={styles.card}>
      <Ionicons name={icon} size={22} color={color} />
      <Text style={[styles.cardValue, { color }]}>{value}</Text>
      <Text style={styles.cardLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  container: { padding: 20, paddingTop: 60 },
  heading: { color: '#f8fafc', fontSize: 26, fontWeight: '700', marginBottom: 20 },
  row: { flexDirection: 'row', gap: 12, marginBottom: 12 },
  card: { flex: 1, backgroundColor: '#1e293b', borderRadius: 14, padding: 16, alignItems: 'center', gap: 4 },
  cardValue: { fontSize: 20, fontWeight: '700' },
  cardLabel: { color: '#64748b', fontSize: 12 },
  section: { backgroundColor: '#1e293b', borderRadius: 14, padding: 16, marginTop: 8 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { color: '#f8fafc', fontSize: 16, fontWeight: '600' },
  seeAll: { color: '#3b82f6', fontSize: 13 },
  eventRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, gap: 10, borderTopWidth: 1, borderTopColor: '#0f172a' },
  eventDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#3b82f6' },
  eventInfo: { flex: 1 },
  eventCamera: { color: '#f8fafc', fontSize: 14, fontWeight: '500' },
  eventMeta: { color: '#64748b', fontSize: 12, marginTop: 2 },
  empty: { color: '#475569', textAlign: 'center', paddingVertical: 12 },
});
