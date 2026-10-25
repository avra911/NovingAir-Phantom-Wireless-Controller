import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  canUnlockLocally,
  loadToken,
  login,
  logout,
  onUnauthorized,
  unlockWithBiometrics,
} from '@/auth';
import { OledColors } from '@/constants/theme';

type Stage = 'loading' | 'locked' | 'login' | 'authed';

const RELOCK_AFTER_MS = 30_000;

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [stage, setStage] = useState<Stage>('loading');
  const [relocked, setRelocked] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const backgroundedAt = useRef<number | null>(null);

  const unlock = useCallback(async () => {
    if (await unlockWithBiometrics()) {
      setRelocked(false);
      setStage('authed');
    } else {
      setStage((current) => (current === 'authed' ? current : 'locked'));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await loadToken();
      if (cancelled) return;
      if (!token) return setStage('login');
      // Without enrolled biometrics or a device PIN the stored token is used as-is.
      if (!(await canUnlockLocally())) return setStage('authed');
      await unlock();
    })();
    return () => {
      cancelled = true;
    };
  }, [unlock]);

  useEffect(
    () =>
      onUnauthorized(() => {
        setRelocked(false);
        setStage('login');
      }),
    [],
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', async (next) => {
      if (next === 'background') {
        backgroundedAt.current = Date.now();
        return;
      }
      if (next !== 'active' || backgroundedAt.current === null) return;
      const away = Date.now() - backgroundedAt.current;
      backgroundedAt.current = null;
      if (stage === 'authed' && away > RELOCK_AFTER_MS && (await canUnlockLocally())) {
        setRelocked(true);
        await unlock();
      }
    });
    return () => subscription.remove();
  }, [stage, unlock]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      setPassword('');
      setStage('authed');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setBusy(false);
    }
  };

  if (stage === 'authed' && !relocked) return <>{children}</>;

  const view = relocked ? 'locked' : stage;
  const screen = (
    <SafeAreaView style={styles.screen}>
      <KeyboardAvoidingView
        style={styles.center}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <Text style={styles.title}>Phantom Remote</Text>
        {view === 'loading' && <ActivityIndicator color={OledColors.mintStrong} />}

        {view === 'locked' && (
          <View style={styles.form}>
            <TouchableOpacity style={styles.button} onPress={unlock}>
              <Text style={styles.buttonText}>Unlock with biometrics</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.link} onPress={logout}>
              <Text style={styles.linkText}>Use password instead</Text>
            </TouchableOpacity>
          </View>
        )}

        {view === 'login' && (
          <View style={styles.form}>
            <TextInput
              style={styles.input}
              placeholder="Username"
              placeholderTextColor={OledColors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="username"
              value={username}
              onChangeText={setUsername}
            />
            <TextInput
              style={styles.input}
              placeholder="Password"
              placeholderTextColor={OledColors.textMuted}
              secureTextEntry
              autoCapitalize="none"
              autoComplete="current-password"
              value={password}
              onChangeText={setPassword}
              onSubmitEditing={submit}
            />
            {error && <Text style={styles.error}>{error}</Text>}
            <TouchableOpacity
              style={[styles.button, (busy || !username || !password) && styles.buttonDisabled]}
              disabled={busy || !username || !password}
              onPress={submit}
            >
              {busy ? (
                <ActivityIndicator color={OledColors.ink} />
              ) : (
                <Text style={styles.buttonText}>Sign in</Text>
              )}
            </TouchableOpacity>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );

  if (!relocked) return screen;

  return (
    <>
      {children}
      <View style={StyleSheet.absoluteFill}>{screen}</View>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: OledColors.ink },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 24 },
  title: { color: OledColors.text, fontSize: 26, fontWeight: '600' },
  form: { width: '100%', maxWidth: 360, gap: 12 },
  input: {
    backgroundColor: OledColors.surface,
    borderColor: OledColors.line,
    borderWidth: 1,
    borderRadius: 10,
    color: OledColors.text,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
  },
  error: { color: OledColors.coral, fontSize: 14 },
  button: {
    backgroundColor: OledColors.mintStrong,
    borderRadius: 10,
    paddingVertical: 13,
    paddingHorizontal: 32,
    alignItems: 'center',
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: OledColors.ink, fontSize: 16, fontWeight: '600' },
  link: { alignItems: 'center', padding: 8 },
  linkText: { color: OledColors.textSecondary, fontSize: 14 },
});
