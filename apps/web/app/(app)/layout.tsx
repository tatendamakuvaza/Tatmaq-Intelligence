"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthScreen } from "@/components/AuthScreen";
import { Alert } from "@/components/ui";
import { useSession } from "@/services/session";

function Onboarding() {
  const { createOrganisation, signOut, profile } = useSession();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  // This screen replaces the sign-up form in place. On a small screen that form has been
  // scrolled to reach its button, and the scroll position would carry over and hide the
  // heading. Start at the top, and focus the field without letting the browser scroll to it.
  useEffect(() => {
    window.scrollTo(0, 0);
    field.current?.focus({ preventScroll: true });
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createOrganisation(name.trim());
    } catch (caught) {
      setError((caught as Error).message);
      setBusy(false);
    }
  }

  return (
    <AuthScreen>
      <form onSubmit={submit}>
        <div className="auth-head">
          <h1>{profile?.full_name ? `Welcome, ${profile.full_name.split(" ")[0]}` : "Welcome"}</h1>
          <p>
            Name the organisation whose data you will analyse. Its datasets, analyses and reports are kept separate
            from every other organisation&apos;s.
          </p>
        </div>
        {error ? <Alert tone="error">{error}</Alert> : null}
        <label className="field">
          <span>Organisation name</span>
          <input ref={field} className="input" required minLength={2} maxLength={200} placeholder="e.g. Mopane Grocers (Pvt) Ltd" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="btn btn-primary btn-block" type="submit" disabled={busy || name.trim().length < 2}>
          {busy ? "Creating..." : "Create organisation"}
        </button>
        <div className="auth-foot">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </form>
    </AuthScreen>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const { status, error, retry } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "signed_out") router.replace("/login");
  }, [status, router]);

  if (status === "needs_organisation") return <Onboarding />;
  if (status === "error") {
    return (
      <div className="splash">
        <div className="stack" style={{ maxWidth: 440, alignItems: "center" }}>
          <Alert tone="error">{error ?? "Something went wrong while loading your account."}</Alert>
          <button className="btn btn-primary" onClick={retry}>
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (status !== "ready") {
    return (
      <div className="splash">
        <div className="spinner" aria-label="Loading" />
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
