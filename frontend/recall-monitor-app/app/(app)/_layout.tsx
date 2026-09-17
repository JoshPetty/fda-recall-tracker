import { Stack } from 'expo-router';

// Everything under this (app) group requires a session (currently just
// scan.tsx, the paste-text product-check flow); the redirect is enforced
// in the root layout (../_layout.tsx), not here.
export default function AppLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
