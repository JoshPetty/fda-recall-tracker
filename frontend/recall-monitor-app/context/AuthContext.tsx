import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react';
import * as Linking from 'expo-linking';
import type { Session } from '@supabase/supabase-js';

import { supabase } from '../lib/supabase';

type AuthContextValue = {
  session: Session | null;
  isLoading: boolean;
  signInWithMagicLink: (email: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load whatever session AsyncStorage already has, then keep it in sync
  // with sign-in/sign-out/token-refresh events.
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setIsLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  // Magic-link emails send the user back into the app via a deep link
  // (recallmonitor://login?code=... on native, the current page's URL on
  // web). Catch that link, whether the app was already open or just
  // launched by it, extract the bare auth code, and exchange it for a
  // session. exchangeCodeForSession expects just the code string, not
  // the full URL.
  useEffect(() => {
    const handleUrl = (url: string) => {
      const code = new URL(url).searchParams.get('code');
      if (!code) return;
      supabase.auth.exchangeCodeForSession(code).catch((error) => {
        console.warn('Failed to exchange magic-link code for a session', error);
      });
    };

    const subscription = Linking.addEventListener('url', (event) => handleUrl(event.url));
    Linking.getInitialURL().then((url) => {
      if (url) handleUrl(url);
    });

    return () => subscription.remove();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isLoading,
      signInWithMagicLink: async (email: string) => {
        const redirectTo = Linking.createURL('login');
        const { error } = await supabase.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: redirectTo },
        });
        return { error: error?.message ?? null };
      },
      signOut: async () => {
        await supabase.auth.signOut();
      },
    }),
    [session, isLoading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}