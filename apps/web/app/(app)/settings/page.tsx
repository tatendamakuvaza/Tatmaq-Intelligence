"use client";

import { useState, type FormEvent } from "react";

import { LearningSettings } from "@/components/LearningSettings";
import { Alert, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { AUTH_MODE } from "@/lib/config";
import { formatBytes, formatInteger, titleCase } from "@/lib/format";
import { api } from "@/services/api";
import { useSession } from "@/services/session";
import type { ClientConfig, Member, Usage } from "@/types/api";

const SIGN_IN: Record<ClientConfig["auth_mode"], string> = {
  dev: "development accounts", builtin: "built-in accounts", supabase: "Supabase Auth",
};
const NO_PASSWORDS = { current: "", next: "", confirm: "" };
const METRICS: Record<string, string> = {
  analyses: "Analyses completed", rows_analysed: "Rows analysed", rows_ingested: "Rows imported", reports: "Report files written",
  storage_bytes: "Bytes uploaded", ai_tokens: "AI tokens used",
};

export default function SettingsPage() {
  const { profile, user, organisation, organisations, selectOrganisation, saveProfile } = useSession();
  const usage = useApi<Usage>("/usage");
  const members = useApi<Member[]>("/organisations/members");
  const config = useApi<ClientConfig>("/config");
  const [name, setName] = useState(profile?.full_name ?? "");
  const [saved, setSaved] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [passwords, setPasswords] = useState(NO_PASSWORDS);
  const [passwordState, setPasswordState] = useState<"idle" | "saving" | "changed">("idle");
  const [passwordError, setPasswordError] = useState<string | null>(null);

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordError(null);
    if (passwords.next.length < 8) return setPasswordError("Choose a new password of at least 8 characters.");
    if (passwords.next !== passwords.confirm) return setPasswordError("The new password and its repeat do not match.");
    setPasswordState("saving");
    try {
      await api.post("/auth/password", { current_password: passwords.current, new_password: passwords.next });
      setPasswords(NO_PASSWORDS);
      setPasswordState("changed");
    } catch (caught) {
      setPasswordError((caught as Error).message);
      setPasswordState("idle");
    }
  }

  function passwordField(key: keyof typeof NO_PASSWORDS, label: string, autoComplete: string, hint?: string) {
    return (
      <label className="field">
        <span>{label}</span>
        <input
          className="input"
          type="password"
          autoComplete={autoComplete}
          maxLength={200}
          value={passwords[key]}
          onChange={(event) => {
            setPasswords({ ...passwords, [key]: event.target.value });
            setPasswordState("idle");
          }}
        />
        {hint ? <small>{hint}</small> : null}
      </label>
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaved("saving");
    setError(null);
    try {
      await saveProfile(name.trim());
      setSaved("saved");
    } catch (caught) {
      setError((caught as Error).message);
      setSaved("idle");
    }
  }

  // Only the built-in sign-in keeps passwords here; with Supabase Auth they belong to Supabase.
  const passwordCard = AUTH_MODE === "builtin" ? (
    <form className="card card-pad stack" onSubmit={changePassword}>
      <div>
        <h2>Password</h2>
        <p className="small muted" style={{ marginTop: 2 }}>If you ever forget it, your administrator can give you a new one.</p>
      </div>
      {passwordError ? <Alert tone="error">{passwordError}</Alert> : null}
      {passwordState === "changed" ? <Alert tone="success">Your password has been changed.</Alert> : null}
      {passwordField("current", "Current password", "current-password")}
      {passwordField("next", "New password", "new-password", "At least 8 characters.")}
      {passwordField("confirm", "Repeat the new password", "new-password")}
      <div className="row">
        <button className="btn btn-primary" disabled={passwordState === "saving" || !passwords.current || !passwords.next || !passwords.confirm}>
          {passwordState === "saving" ? "Changing..." : "Change password"}
        </button>
      </div>
    </form>
  ) : null;

  const usageCard = (
    <section className="card">
      <div className="card-head"><h2>Usage this month</h2></div>
      {usage.data ? (
        <table className="table table-compact">
          <tbody>
            <tr>
              <td>Analyses against allowance</td>
              <td className="right"><strong>{formatInteger(usage.data.analyses.used)}</strong> of {formatInteger(usage.data.analyses.limit)}</td>
            </tr>
            {Object.entries(usage.data.this_month).map(([metric, value]) => (
              <tr key={metric}>
                <td>{METRICS[metric] ?? titleCase(metric)}</td>
                <td className="right">{metric === "storage_bytes" ? formatBytes(value) : formatInteger(value)}</td>
              </tr>
            ))}
            <tr><td className="muted">Largest file accepted</td><td className="right muted">{usage.data.limits.max_upload_mb} MB</td></tr>
            <tr><td className="muted">Most rows per dataset</td><td className="right muted">{formatInteger(usage.data.limits.max_analysis_rows)}</td></tr>
          </tbody>
        </table>
      ) : usage.error ? (
        <div className="card-pad"><Alert tone="error">{usage.error.message}</Alert></div>
      ) : (
        <Loading />
      )}
    </section>
  );

  const peopleCard = (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>People</h2>
          <p>Inviting colleagues is not available yet.</p>
        </div>
      </div>
      {members.data ? (
        <table className="table table-compact">
          <tbody>
            {members.data.map((member) => (
              <tr key={member.user_id}>
                <td>
                  <strong>{member.full_name ?? member.email}</strong>
                  <div className="small muted">{member.email}</div>
                </td>
                <td className="right"><span className="badge">{titleCase(member.role)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Loading />
      )}
    </section>
  );

  return (
    <>
      <PageHeader title="Settings">Your profile, your organisation, agent learning and this month&apos;s usage.</PageHeader>
      <div className="grid grid-2">
        <form className="card card-pad stack" onSubmit={submit}>
          <h2>Your profile</h2>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <label className="field">
            <span>Name</span>
            <input className="input" value={name} maxLength={200} onChange={(event) => { setName(event.target.value); setSaved("idle"); }} />
          </label>
          <label className="field">
            <span>Email</span>
            <input className="input" value={user?.email ?? ""} disabled />
          </label>
          <div className="row">
            <button className="btn btn-primary" disabled={saved === "saving" || !name.trim()}>
              {saved === "saving" ? "Saving..." : "Save"}
            </button>
            {saved === "saved" ? <span className="small" style={{ color: "var(--blue-700)", fontWeight: 600 }}>Saved</span> : null}
          </div>
        </form>

        <section className="card card-pad stack">
          <h2>Organisation</h2>
          {organisations.length > 1 ? (
            <label className="field">
              <span>Working in</span>
              <select className="select" value={organisation?.id} onChange={(event) => void selectOrganisation(event.target.value)}>
                {organisations.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
          ) : null}
          <table className="table table-compact">
            <tbody>
              <tr><td className="muted">Name</td><td>{organisation?.name}</td></tr>
              <tr><td className="muted">Your role</td><td>{titleCase(organisation?.role ?? "")}</td></tr>
              <tr><td className="muted">Reporting currency</td><td>{organisation?.default_currency} <span className="muted small">(used when a dataset has no currency column)</span></td></tr>
              <tr><td className="muted">Ambiguous dates</td><td>{organisation?.date_order === "DMY" ? "Read as day/month/year" : "Read as month/day/year"}</td></tr>
              <tr><td className="muted">Time zone</td><td>{organisation?.timezone}</td></tr>
            </tbody>
          </table>
        </section>
      </div>

      <LearningSettings />

      {passwordCard ? (
        <>
          <div className="grid grid-2">
            {passwordCard}
            {peopleCard}
          </div>
          {usageCard}
        </>
      ) : (
        <div className="grid grid-2">
          {usageCard}
          {peopleCard}
        </div>
      )}
      {config.data ? (
        <p className="tiny muted">
          TATMAQ Intelligence {config.data.version} &middot; sign-in: {SIGN_IN[config.data.auth_mode]} &middot; AI model: {config.data.ai_enabled ? "connected" : "not connected"}
        </p>
      ) : null}
    </>
  );
}
