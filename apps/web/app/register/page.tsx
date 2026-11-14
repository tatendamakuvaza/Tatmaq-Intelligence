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

export default function RegisterPage() {
  const { status, signUp } = useSession();
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [slow, setSlow] = useState(false);
  const config = useApi<ClientConfig>("/config");

  useEffect(() => {
    if (status === "ready" || status === "needs_organisation") router.replace("/dashboard");
  }, [status, router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 8) return setError("Choose a password of at least 8 characters.");
    setBusy(true);
    setError(null);
    try {
      const result = await noticeIfSlow(setSlow, () => signUp(email.trim(), password, fullName.trim()));
      if (result.confirmEmail) setConfirm(true);
    } catch (caught) {
      setError((caught as Error).message);
    }
    setBusy(false);
  }

  return (
    <AuthScreen>
      {config.data?.signups_open === false ? (
        <div className="auth-body">
          <div className="auth-head">
            <h1>Sign-ups are closed</h1>
          </div>
          <Alert tone="info">New accounts are created by the administrator. Ask them to set one up for you.</Alert>
          <Link className="btn btn-primary btn-block" href="/login">
            Go to sign in
          </Link>
        </div>
      ) : confirm ? (
        <div className="auth-body">
          <div className="auth-head">
            <h1>Check your email</h1>
          </div>
          <Alert tone="success">
            We sent a confirmation link to <strong>{email}</strong>. Open it, then come back and sign in.
          </Alert>
          <Link className="btn btn-primary btn-block" href="/login">
            Go to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} noValidate>
          <div className="auth-head">
            <h1>Create your account</h1>
            <p>You will set up your organisation in the next step.</p>
          </div>
          {error ? <Alert tone="error">{error}</Alert> : null}
          {slow ? <Alert tone="info">{SERVER_STARTING}</Alert> : null}
          <label className="field">
            <span>Your name</span>
            <input className="input" autoComplete="name" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </label>
          <label className="field">
            <span>Work email</span>
            <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span>Password</span>
            <input className="input" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
            <small>At least 8 characters.</small>
          </label>
          <button className="btn btn-primary btn-block" type="submit" disabled={busy || !email || !password || !fullName}>
            {busy ? "Creating account..." : "Create account"}
          </button>
          <div className="auth-foot">
            <p className="small muted">
              Already have an account? <Link href="/login">Sign in</Link>
            </p>
          </div>
        </form>
      )}
    </AuthScreen>
  );
}
