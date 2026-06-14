import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Image, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { FaceEnrollment } from '../types';

interface Props {
  enrollment: FaceEnrollment;
  onDelete: () => void;
}

export default function FaceCard({ enrollment, onDelete }: Props) {
  return (
    <View style={styles.card}>
      {enrollment.image_b64 ? (
        <Image source={{ uri: enrollment.image_b64 }} style={styles.photo} resizeMode="cover" />
      ) : (
        <View style={[styles.photo, styles.photoPlaceholder]}>
          <Ionicons name="person-outline" size={32} color="#475569" />
        </View>
      )}
      <Text style={styles.name} numberOfLines={1}>{enrollment.name}</Text>
      {enrollment.label ? (
        <Text style={styles.label} numberOfLines={1}>{enrollment.label}</Text>
      ) : null}
      <Text style={styles.date}>
        {new Date(enrollment.created_at).toLocaleDateString()}
      </Text>
      <TouchableOpacity style={styles.deleteBtn} onPress={onDelete}>
        <Ionicons name="trash-outline" size={16} color="#ef4444" />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: '#1e293b',
    borderRadius: 14,
    padding: 12,
    alignItems: 'center',
    position: 'relative',
  },
  photo: { width: 80, height: 80, borderRadius: 40, marginBottom: 8 },
  photoPlaceholder: { backgroundColor: '#0f172a', alignItems: 'center', justifyContent: 'center' },
  name: { color: '#f8fafc', fontSize: 14, fontWeight: '600', textAlign: 'center' },
  label: { color: '#3b82f6', fontSize: 12, marginTop: 2, textAlign: 'center' },
  date: { color: '#475569', fontSize: 11, marginTop: 4 },
  deleteBtn: { position: 'absolute', top: 8, right: 8, padding: 4 },
});
