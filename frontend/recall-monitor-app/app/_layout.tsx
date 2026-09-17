import { useEffect } from 'react';
import { Slot, useRouter, useSegments } from 'expo-router';
import { ActivityIndicator, View } from 'react-native';

import { AuthProvider, useAuth } from '../context/AuthContext';

// Routes that must stay reachable without a session, even if a route ever
// ends up nested under the (app) group by mistake. Recall browsing/search
// is public by design (see app/recalls/); everything else under (app),
// e.g. the paste-text product-check screen, stays gated.
const PUBLIC_ROUTE_SEGMENTS = new Set(['recalls']);

function RootNavigation() {
  const { session, isLoading } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;

    const firstSegment = segments[0];
    const isPublicRoute = firstSegment === undefined || PUBLIC_ROUTE_SEGMENTS.has(firstSegment);
    const inProtectedGroup = firstSegment === '(app)';
    const onLoginScreen = firstSegment === 'login';

    if (!session && inProtectedGroup && !isPublicRoute) {
      router.replace('/login');
    } else if (session && onLoginScreen) {
      router.replace('/');
    }
  }, [session, isLoading, segments, router]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }

  return <Slot />;
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <RootNavigation />
    </AuthProvider>
  );
}
