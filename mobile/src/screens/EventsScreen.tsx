import { useQuery } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React, { useState } from 'react';
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { fetchEvents } from '../api/events';
import { CctvEvent, RootStackParamList } from '../types';
import EventCard from '../components/EventCard';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const LABELS = ['', 'person', 'car', 'animal', 'package'];

export default function EventsScreen() {
  const nav = useNavigation<Nav>();
  const [camera, setCamera] = useState('');
  const [label, setLabel] = useState('');

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['events', { camera, label }],
    queryFn: () => fetchEvents({ camera: camera || undefined, label: label || undefined, limit: 50 }),
  });

  return (
    <View style={styles.root}>
      <Text style={styles.heading}>Events</Text>

      {/* Filters */}
      <TextInput
        style={styles.input}
        placeholder="Filter by camera…"
        placeholderTextColor="#64748b"
        value={camera}
        onChangeText={setCamera}
      />

      <View style={styles.chips}>
        {LABELS.map((l) => (
          <TouchableOpacity
            key={l}
            style={[styles.chip, label === l && styles.chipActive]}
            onPress={() => setLabel(l)}
          >
            <Text style={[styles.chipText, label === l && styles.chipTextActive]}>
              {l || 'All'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={data}
        keyExtractor={(e) => e.id}
        renderItem={({ item }) => (
          <EventCard event={item} onPress={() => nav.navigate('EventDetail', { event: item })} />
        )}
        refreshControl={
          <RefreshControl refreshing={isFetching} onRefresh={refetch} tintColor="#3b82f6" />
        }
        ListEmptyComponent={
          <Text style={styles.empty}>{isLoading ? 'Loading…' : 'No events found.'}</Text>
        }
        contentContainerStyle={{ paddingBottom: 20 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a', paddingTop: 60, paddingHorizontal: 16 },
  heading: { color: '#f8fafc', fontSize: 26, fontWeight: '700', marginBottom: 14 },
  input: {
    backgroundColor: '#1e293b',
    color: '#f8fafc',
    borderRadius: 10,
    padding: 10,
    fontSize: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#334155',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 14 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 20, backgroundColor: '#1e293b', borderWidth: 1, borderColor: '#334155' },
  chipActive: { backgroundColor: '#3b82f6', borderColor: '#3b82f6' },
  chipText: { color: '#94a3b8', fontSize: 13 },
  chipTextActive: { color: '#fff' },
  empty: { color: '#475569', textAlign: 'center', marginTop: 40 },
});
