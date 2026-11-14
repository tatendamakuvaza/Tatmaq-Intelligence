// Sign-in behind one interface, with two implementations:
//   - the API's own built-in sign-in (accounts kept in the application's database)
//   - Supabase Auth, used when NEXT_PUBLIC_SUPABASE_* are set
// The rest of the app only ever asks for "the current access token".

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { API_BASE, AUTH_MODE, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from "@/lib/config";
import { safeStorage } from "@/lib/storage";

export type AuthUser = { id: string; email: string | null };
export type AuthSession = { token: string; user: AuthUser };
export type SignUpResult = { session: AuthSession | null; confirmEmail: boolean };

export class AuthError extends Error {}

const SESSION_KEY = "tatmaq:session";

type StoredSession = AuthSession & { expiresAt: number };

async function builtinRequest(path: "login" | "register", email: string, password: string): Promise<AuthSession> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch {
    throw new AuthError("Could not reach the server. Check your connection and try again.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new AuthError(body?.error?.message ?? "Sign-in failed. Please try again.");
  const session: StoredSession = {
    token: body.access_token,
    user: body.user,
    expiresAt: Date.now() + (body.expires_in - 60) * 1000,
  };
  safeStorage.set(SESSION_KEY, JSON.stringify(session));
  return { token: session.token, user: session.user };
}

const builtinAuth = {
  async current(): Promise<AuthSession | null> {
    const raw = safeStorage.get(SESSION_KEY);
    if (!raw) return null;
    try {
      const stored = JSON.parse(raw) as StoredSession;
      if (stored.expiresAt > Date.now()) return { token: stored.token, user: stored.user };
    } catch {
      /* fall through and clear */
    }
    safeStorage.remove(SESSION_KEY);
    return null;
  },
  signIn: (email: string, password: string) => builtinRequest("login", email, password),
  async signUp(email: string, password: string): Promise<SignUpResult> {
    return { session: await builtinRequest("register", email, password), confirmEmail: false };
  },
  async signOut(): Promise<void> {
    safeStorage.remove(SESSION_KEY);
  },
};

let supabaseClient: SupabaseClient | null = null;

function supabase(): SupabaseClient {
  supabaseClient ??= createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
  return supabaseClient;
}

const supabaseAuth = {
  async current(): Promise<AuthSession | null> {
    // getSession() refreshes an expired access token before returning it.
    const { data } = await supabase().auth.getSession();
    const session = data.session;
    return session ? { token: session.access_token, user: { id: session.user.id, email: session.user.email ?? null } } : null;
  },
  async signIn(email: string, password: string): Promise<AuthSession> {
    const { data, error } = await supabase().auth.signInWithPassword({ email, password });
    if (error || !data.session) throw new AuthError(error?.message ?? "Sign-in failed. Please try again.");
    return { token: data.session.access_token, user: { id: data.user.id, email: data.user.email ?? null } };
  },
  async signUp(email: string, password: string): Promise<SignUpResult> {
    const { data, error } = await supabase().auth.signUp({ email, password });
    if (error) throw new AuthError(error.message);
    if (!data.session || !data.user) return { session: null, confirmEmail: true };
    return {
      session: { token: data.session.access_token, user: { id: data.user.id, email: data.user.email ?? null } },
      confirmEmail: false,
    };
  },
  async signOut(): Promise<void> {
    await supabase().auth.signOut();
  },
};

export const auth = AUTH_MODE === "supabase" ? supabaseAuth : builtinAuth;
