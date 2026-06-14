import { useQuery } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { fetchCameras, fetchCameraHealth } from '../api/cameras';
import { Camera, RootStackParamList } from '../types';
import CameraCard from '../components/CameraCard';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function CameraListScreen() {
  const nav = useNavigation<Nav>();

  const cams = useQuery({ queryKey: ['cameras'], queryFn: fetchCameras });
  const health = useQuery({ queryKey: ['cameraHealth'], queryFn: fetchCameraHealth, refetchInterval: 30_000 });

  const healthMap = Object.fromEntries(
    (health.data?.cameras ?? []).map((h) => [h.camera_name, h.status]),
  );

  const refreshing = cams.isFetching || health.isFetching;
  const refetch = () => { cams.refetch(); health.refetch(); };

  return (
    <View style={styles.root}>
      <Text style={styles.heading}>Cameras</Text>
      <FlatList
        data={cams.data}
        keyExtractor={(c) => c.id}
        renderItem={({ item }: { item: Camera }) => (
          <CameraCard
            camera={item}
            status={healthMap[item.name] ?? 'unknown'}
            onPress={() => nav.navigate('CameraDetail', { camera: item })}
          />
        )}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refetch} tintColor="#3b82f6" />
        }
        ListEmptyComponent={
          <Text style={styles.empty}>{cams.isLoading ? 'Loading…' : 'No cameras found.'}</Text>
        }
        contentContainerStyle={{ paddingBottom: 20 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a', paddingTop: 60, paddingHorizontal: 16 },
  heading: { color: '#f8fafc', fontSize: 26, fontWeight: '700', marginBottom: 16 },
  empty: { color: '#475569', textAlign: 'center', marginTop: 40 },
});
