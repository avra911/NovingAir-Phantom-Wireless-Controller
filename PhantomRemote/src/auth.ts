import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

const TOKEN_KEY = 'phantom_auth_token';
const isNative = Platform.OS !== 'web';

// On web the token lives in memory only, so a reload requires a new password login.
let memoryToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export async function loadToken(): Promise<string | null> {
  if (!isNative) return memoryToken;
  memoryToken = await SecureStore.getItemAsync(TOKEN_KEY);
  return memoryToken;
}

async function saveToken(token: string | null) {
  memoryToken = token;
  if (!isNative) return;
  if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
}

export async function logout() {
  await saveToken(null);
  unauthorizedListeners.forEach((listener) => listener());
}

export function onUnauthorized(listener: () => void) {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

export async function login(username: string, password: string) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (res.status === 401) throw new Error('Invalid username or password.');
  if (res.status === 429) throw new Error('Too many attempts. Try again in a few minutes.');
  if (!res.ok) throw new Error(`Login failed (HTTP ${res.status}).`);
  const { token } = await res.json();
  await saveToken(token);
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (memoryToken) headers.set('Authorization', `Bearer ${memoryToken}`);
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401) await logout();
  return res;
}

/** True when the device can prompt for biometrics or a device PIN. */
export async function canUnlockLocally() {
  if (!isNative) return false;
  return (
    (await LocalAuthentication.hasHardwareAsync()) &&
    (await LocalAuthentication.isEnrolledAsync())
  );
}

export async function unlockWithBiometrics() {
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Unlock Phantom Remote',
    cancelLabel: 'Use password',
  });
  return result.success;
}
