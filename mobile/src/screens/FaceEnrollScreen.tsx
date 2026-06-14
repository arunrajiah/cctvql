import { Ionicons } from '@expo/vector-icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigation } from '@react-navigation/native';
import * as ImagePicker from 'expo-image-picker';
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { enrollFace } from '../api/faces';

export default function FaceEnrollScreen() {
  const nav = useNavigation();
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [label, setLabel] = useState('');
  const [imageUri, setImageUri] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => enrollFace(name.trim(), label.trim(), imageUri!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['faces'] });
      Alert.alert('Enrolled', `${name} has been added to the face registry.`, [
        { text: 'OK', onPress: () => nav.goBack() },
      ]);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Enrolment failed.';
      Alert.alert('Error', msg);
    },
  });

  const pickImage = async (source: 'camera' | 'library') => {
    let result;
    if (source === 'camera') {
      const { status } = await ImagePicker.requestCameraPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Permission needed', 'Camera permission is required to take photos.');
        return;
      }
      result = await ImagePicker.launchCameraAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8,
        allowsEditing: true,
        aspect: [1, 1],
      });
    } else {
      result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8,
        allowsEditing: true,
        aspect: [1, 1],
      });
    }
    if (!result.canceled && result.assets[0]) {
      setImageUri(result.assets[0].uri);
    }
  };

  const canSubmit = name.trim().length > 0 && !!imageUri && !mutation.isPending;

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        {/* Photo picker */}
        <View style={styles.photoSection}>
          {imageUri ? (
            <Image source={{ uri: imageUri }} style={styles.photo} />
          ) : (
            <View style={styles.photoPlaceholder}>
              <Ionicons name="person-outline" size={60} color="#475569" />
            </View>
          )}
          <View style={styles.photoButtons}>
            <TouchableOpacity style={styles.photoBtn} onPress={() => pickImage('camera')}>
              <Ionicons name="camera-outline" size={18} color="#3b82f6" />
              <Text style={styles.photoBtnText}>Camera</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.photoBtn} onPress={() => pickImage('library')}>
              <Ionicons name="images-outline" size={18} color="#3b82f6" />
              <Text style={styles.photoBtnText}>Library</Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.hint}>Use a clear, well-lit frontal photo with one person.</Text>
        </View>

        {/* Form */}
        <View style={styles.card}>
          <Text style={styles.fieldLabel}>Full name *</Text>
          <TextInput
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholder="Alice Smith"
            placeholderTextColor="#64748b"
          />

          <Text style={styles.fieldLabel}>Label / role (optional)</Text>
          <TextInput
            style={styles.input}
            value={label}
            onChangeText={setLabel}
            placeholder="resident, employee, visitor…"
            placeholderTextColor="#64748b"
          />
        </View>

        <TouchableOpacity
          style={[styles.button, !canSubmit && styles.buttonDisabled]}
          onPress={() => mutation.mutate()}
          disabled={!canSubmit}
        >
          {mutation.isPending ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="checkmark-circle-outline" size={20} color="#fff" />
              <Text style={styles.buttonText}>Enrol Face</Text>
            </>
          )}
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  container: { padding: 20, paddingBottom: 40 },
  photoSection: { alignItems: 'center', marginBottom: 24, gap: 12 },
  photo: { width: 160, height: 160, borderRadius: 80, backgroundColor: '#1e293b' },
  photoPlaceholder: { width: 160, height: 160, borderRadius: 80, backgroundColor: '#1e293b', alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: '#334155', borderStyle: 'dashed' },
  photoButtons: { flexDirection: 'row', gap: 12 },
  photoBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#1e293b', borderRadius: 10, paddingHorizontal: 16, paddingVertical: 10, borderWidth: 1, borderColor: '#334155' },
  photoBtnText: { color: '#3b82f6', fontSize: 14 },
  hint: { color: '#475569', fontSize: 12, textAlign: 'center', paddingHorizontal: 20 },
  card: { backgroundColor: '#1e293b', borderRadius: 14, padding: 16, marginBottom: 20 },
  fieldLabel: { color: '#94a3b8', fontSize: 13, marginBottom: 6, marginTop: 10 },
  input: { backgroundColor: '#0f172a', color: '#f8fafc', borderRadius: 10, padding: 12, fontSize: 15, borderWidth: 1, borderColor: '#334155' },
  button: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: '#3b82f6', borderRadius: 12, padding: 16 },
  buttonDisabled: { opacity: 0.4 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
