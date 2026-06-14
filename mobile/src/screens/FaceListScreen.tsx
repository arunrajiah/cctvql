import { Ionicons } from '@expo/vector-icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import React from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { deleteFace, fetchFaces } from '../api/faces';
import FaceCard from '../components/FaceCard';
import { RootStackParamList } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export default function FaceListScreen() {
  const nav = useNavigation<Nav>();
  const qc = useQueryClient();

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['faces'],
    queryFn: fetchFaces,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteFace,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['faces'] }),
    onError: () => Alert.alert('Error', 'Could not delete enrollment.'),
  });

  const confirmDelete = (faceId: string, name: string) => {
    Alert.alert(
      'Remove enrollment',
      `Remove "${name}" from the face registry?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: () => deleteMutation.mutate(faceId) },
      ],
    );
  };

  return (
    <View style={styles.root}>
      <FlatList
        data={data}
        keyExtractor={(f) => f.face_id}
        numColumns={2}
        columnWrapperStyle={{ gap: 12 }}
        renderItem={({ item }) => (
          <FaceCard
            enrollment={item}
            onDelete={() => confirmDelete(item.face_id, item.name)}
          />
        )}
        refreshControl={
          <RefreshControl refreshing={isFetching} onRefresh={refetch} tintColor="#3b82f6" />
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Ionicons name="person-add-outline" size={48} color="#334155" />
            <Text style={styles.emptyText}>No faces enrolled yet.</Text>
            <Text style={styles.emptySubtext}>Tap + to add a person.</Text>
          </View>
        }
        ListHeaderComponent={<Text style={styles.count}>{data?.length ?? 0} enrolled</Text>}
        contentContainerStyle={{ padding: 16, paddingBottom: 100 }}
      />

      {!isLoading && (
        <TouchableOpacity style={styles.fab} onPress={() => nav.navigate('FaceEnroll')}>
          <Ionicons name="person-add" size={22} color="#fff" />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  count: { color: '#64748b', fontSize: 13, marginBottom: 12 },
  empty: { alignItems: 'center', paddingTop: 60, gap: 8 },
  emptyText: { color: '#475569', fontSize: 16, fontWeight: '600' },
  emptySubtext: { color: '#334155', fontSize: 13 },
  fab: { position: 'absolute', right: 20, bottom: 24, width: 56, height: 56, borderRadius: 28, backgroundColor: '#3b82f6', alignItems: 'center', justifyContent: 'center', elevation: 4 },
});
