"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AuthScreen } from "@/components/AuthScreen";
import { Alert } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { noticeIfSlow, SERVER_STARTING } from "@/lib/slow";
import { useSession } from "@/services/session";
import type { ClientConfig } from "@/types/api";

export default function LoginPage() {
  const { status, signIn } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  // Asking for this as the page opens also starts waking a sleeping server before anyone types.
  const config = useApi<ClientConfig>("/config");

  useEffect(() => {
    if (status === "ready" || status === "needs_organisation") router.replace("/dashboard");
  }, [status, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await noticeIfSlow(setSlow, () => signIn(email.trim(), password));
    } catch (caught) {
      setError((caught as Error).message);
      setBusy(false);
    }
  }

  return (
    <AuthScreen>
      <form onSubmit={submit} noValidate>
        <div className="auth-head">
          <h1>Sign in</h1>
          <p>Welcome back. Enter your details to continue.</p>
        </div>
        {error ? <Alert tone="error">{error}</Alert> : null}
        {slow ? <Alert tone="info">{SERVER_STARTING}</Alert> : null}
        <label className="field">
          <span>Email</span>
          <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Password</span>
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button className="btn btn-primary btn-block" type="submit" disabled={busy || !email || !password}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
        <div className="auth-foot">
          {config.data?.signups_open === false ? (
            <p className="small muted">Need an account? Ask your administrator to create one for you.</p>
          ) : (
            <p className="small muted">
              New to TATMAQ Intelligence? <Link href="/register">Create an account</Link>
            </p>
          )}
          {config.data?.auth_mode === "dev" ? (
            <p className="tiny muted">Development sign-in is active: accounts live in this installation&apos;s own database.</p>
          ) : null}
        </div>
      </form>
    </AuthScreen>
  );
}
