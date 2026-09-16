import { Button, StyleSheet, Text, View } from 'react-native';
import { Link } from 'expo-router';

import { useAuth } from '../context/AuthContext';

export default function HomeScreen() {
  const { session, signOut } = useAuth();

  if (!session) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Recall Monitor</Text>
        <Text style={styles.body}>
          Search and browse food recall records without an account. Sign in to check your own
          receipts against them.
        </Text>
        <Link href="/recalls" style={styles.link}>
          Browse recalls
        </Link>
        <Link href="/login" style={styles.link}>
          Sign in
        </Link>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Recall Monitor</Text>
      <Text>Signed in as {session.user.email}</Text>
      <Link href="/recalls" style={styles.link}>
        View recalls
      </Link>
      <Link href="/scan" style={styles.link}>
        Check a product
      </Link>
      <Button title="Sign out" onPress={signOut} />
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
  link: {
    fontSize: 16,
  },
});
