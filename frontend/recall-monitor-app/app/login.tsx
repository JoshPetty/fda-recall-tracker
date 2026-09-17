import { useState } from 'react';
import { ActivityIndicator, Button, StyleSheet, Text, TextInput, View } from 'react-native';

import { useAuth } from '../context/AuthContext';

type Status = 'idle' | 'sending' | 'sent' | 'error';

export default function LoginScreen() {
  const { signInWithMagicLink } = useAuth();
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async () => {
    const trimmed = email.trim();
    if (!trimmed) return;

    setStatus('sending');
    setErrorMessage(null);

    const { error } = await signInWithMagicLink(trimmed);
    if (error) {
      setStatus('error');
      setErrorMessage(error);
    } else {
      setStatus('sent');
    }
  };

  if (status === 'sent') {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Check your email</Text>
        <Text style={styles.body}>We sent a sign-in link to {email.trim()}.</Text>
        <Button title="Use a different email" onPress={() => setStatus('idle')} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Sign in</Text>
      <TextInput
        style={styles.input}
        placeholder="you@example.com"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        editable={status !== 'sending'}
      />
      <Button
        title={status === 'sending' ? 'Sending…' : 'Send magic link'}
        onPress={handleSubmit}
        disabled={status === 'sending' || !email.trim()}
      />
      {status === 'sending' && <ActivityIndicator />}
      {status === 'error' && errorMessage ? <Text style={styles.error}>{errorMessage}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 24,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
  },
  body: {
    textAlign: 'center',
  },
  input: {
    width: '100%',
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 12,
  },
  error: {
    color: '#c0392b',
  },
});
