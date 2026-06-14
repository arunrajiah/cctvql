import { Ionicons } from '@expo/vector-icons';
import React, { useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { sendQuery, clearSession } from '../api/query';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  ts: string;
}

let _sessionId: string | undefined;

export default function ChatScreen() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const listRef = useRef<FlatList>(null);

  const push = (role: 'user' | 'assistant', text: string) => {
    const msg: Message = { id: Date.now().toString(), role, text, ts: new Date().toISOString() };
    setMessages((prev) => [...prev, msg]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    return msg;
  };

  const send = async () => {
    const q = input.trim();
    if (!q || loading) return;
    setInput('');
    push('user', q);
    setLoading(true);
    try {
      const resp = await sendQuery(q, _sessionId);
      _sessionId = resp.session_id;
      push('assistant', resp.answer);
    } catch (err: unknown) {
      push('assistant', `⚠️ ${err instanceof Error ? err.message : 'Request failed.'}`);
    } finally {
      setLoading(false);
    }
  };

  const reset = async () => {
    if (_sessionId) {
      await clearSession(_sessionId).catch(() => {});
      _sessionId = undefined;
    }
    setMessages([]);
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.heading}>Ask</Text>
        {messages.length > 0 && (
          <TouchableOpacity onPress={reset}>
            <Text style={styles.resetBtn}>New chat</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Messages */}
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        style={{ flex: 1 }}
        contentContainerStyle={styles.msgList}
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === 'user' ? styles.userBubble : styles.aiBubble]}>
            <Text style={styles.bubbleText}>{item.text}</Text>
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="chatbubbles-outline" size={48} color="#334155" />
            <Text style={styles.emptyTitle}>Ask anything</Text>
            <Text style={styles.emptySub}>
              "Was there anyone near the front door last night?"
            </Text>
            <Text style={styles.emptySub}>"Show all cameras offline"</Text>
            <Text style={styles.emptySub}>"Any unusual activity this week?"</Text>
          </View>
        }
      />

      {loading && (
        <View style={styles.typingRow}>
          <ActivityIndicator size="small" color="#3b82f6" />
          <Text style={styles.typingText}>Thinking…</Text>
        </View>
      )}

      {/* Input bar */}
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="Ask about your cameras…"
          placeholderTextColor="#475569"
          multiline
          returnKeyType="send"
          onSubmitEditing={send}
          blurOnSubmit={false}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!input.trim() || loading) && styles.sendBtnDisabled]}
          onPress={send}
          disabled={!input.trim() || loading}
        >
          <Ionicons name="send" size={18} color="#fff" />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f172a' },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 20, paddingTop: 60, paddingBottom: 10 },
  heading: { color: '#f8fafc', fontSize: 26, fontWeight: '700' },
  resetBtn: { color: '#3b82f6', fontSize: 14 },
  msgList: { padding: 16, paddingBottom: 8 },
  bubble: { maxWidth: '80%', borderRadius: 16, padding: 12, marginBottom: 8 },
  userBubble: { alignSelf: 'flex-end', backgroundColor: '#3b82f6' },
  aiBubble: { alignSelf: 'flex-start', backgroundColor: '#1e293b' },
  bubbleText: { color: '#f8fafc', fontSize: 15, lineHeight: 21 },
  typingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 20, paddingBottom: 6 },
  typingText: { color: '#64748b', fontSize: 13 },
  inputRow: { flexDirection: 'row', alignItems: 'flex-end', padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: '#1e293b' },
  input: { flex: 1, backgroundColor: '#1e293b', color: '#f8fafc', borderRadius: 22, paddingHorizontal: 16, paddingVertical: 10, fontSize: 15, maxHeight: 120, borderWidth: 1, borderColor: '#334155' },
  sendBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#3b82f6', alignItems: 'center', justifyContent: 'center' },
  sendBtnDisabled: { backgroundColor: '#334155' },
  emptyState: { alignItems: 'center', paddingTop: 60, gap: 10 },
  emptyTitle: { color: '#475569', fontSize: 18, fontWeight: '600', marginTop: 8 },
  emptySub: { color: '#334155', fontSize: 13, fontStyle: 'italic' },
});
