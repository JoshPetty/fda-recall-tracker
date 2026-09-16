import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, View, Pressable } from 'react-native';
import { Link } from 'expo-router';

import { useAuth } from '../../context/AuthContext';

type MatchResult = {
  recall_id: string;
  confidence: number;
  method: string;
  match_features: Record<string, unknown>;
  recall_product_name: string | null;
};

type Status = 'idle' | 'checking' | 'done' | 'error';

const API_URL = process.env.EXPO_PUBLIC_API_URL;

export default function ScanScreen() {
  const { session } = useAuth();
  const [text, setText] = useState('');
  const [brand, setBrand] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [results, setResults] = useState<MatchResult[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = text.trim();
    if (!trimmed || !session) return;

    setStatus('checking');
    setErrorMessage(null);

    try {
      const response = await fetch(`${API_URL}/match`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          text: trimmed,
          brand: brand.trim() || undefined,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Request failed (${response.status})`);
      }

      const data: MatchResult[] = await response.json();
      setResults(data);
      setStatus('done');
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Something went wrong.');
      setStatus('error');
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Link href="/" style={styles.back}>
        Back
      </Link>
      <Text style={styles.title}>Check a product</Text>
      <Text style={styles.body}>Paste or type a product name to check it against known recalls.</Text>

      <TextInput
        style={styles.input}
        placeholder="Product name"
        value={text}
        onChangeText={setText}
        editable={status !== 'checking'}
        multiline
      />
      <TextInput
        style={styles.input}
        placeholder="Brand (optional)"
        value={brand}
        onChangeText={setBrand}
        editable={status !== 'checking'}
      />

      <Pressable
        style={[styles.submitButton, (!text.trim() || status === 'checking') && styles.submitButtonDisabled]}
        onPress={handleSubmit}
        disabled={!text.trim() || status === 'checking'}
      >
        <Text style={styles.submitButtonText}>{status === 'checking' ? 'Checking…' : 'Check for recalls'}</Text>
      </Pressable>

      {status === 'checking' && <ActivityIndicator />}

      {status === 'error' && errorMessage ? <Text style={styles.error}>{errorMessage}</Text> : null}

      {status === 'done' && results.length === 0 ? (
        <Text style={styles.body}>No match found.</Text>
      ) : null}

      {status === 'done' && results.length > 0 ? (
        <View style={styles.results}>
          {results.map((result) => (
            <View key={result.recall_id} style={styles.resultRow}>
              <Text style={styles.resultTitle}>{result.recall_product_name ?? 'Unnamed recall'}</Text>
              <Text style={styles.resultMeta}>Confidence: {Math.round(result.confidence * 100)}%</Text>
              <Text style={styles.resultMeta}>Method: {result.method}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    padding: 24,
    gap: 12,
  },
  back: {
    fontSize: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
  },
  body: {
    fontSize: 16,
  },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
  },
  submitButton: {
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  submitButtonDisabled: {
    backgroundColor: '#999',
  },
  submitButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  error: {
    color: '#c0392b',
  },
  results: {
    gap: 12,
    marginTop: 8,
  },
  resultRow: {
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 8,
    padding: 12,
    gap: 4,
  },
  resultTitle: {
    fontSize: 16,
    fontWeight: '600',
  },
  resultMeta: {
    fontSize: 14,
    color: '#555',
  },
});
