"use client";

import { GraduationCap } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert, Loading } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/services/api";
import { useSession } from "@/services/session";
import type { LearningProfile, ReportStyle } from "@/types/api";

const STYLES: [ReportStyle, string][] = [
  ["executive", "Executive — short, decision-focused summaries"],
  ["balanced", "Balanced — a concise summary with supporting detail"],
  ["detailed", "Detailed — fuller explanations for analysts"],
];

type Form = { business_context: string; glossary: string; analysis_preferences: string; report_style: ReportStyle };
const EMPTY: Form = { business_context: "", glossary: "", analysis_preferences: "", report_style: "executive" };

/**
 * The organisation's durable guidance for the agents: business context, a
 * glossary, analysis preferences, report style and lessons from feedback.
 * Owners and admins edit it; everyone in the organisation can read it.
 */
export function LearningSettings() {
  const { can } = useSession();
  // Owners and admins edit the whole profile; the bridge agent role may only add lessons.
  const editable = can("organisation:manage");
  const canTeach = can("learning:write");
  const profile = useApi<LearningProfile>("/organisations/learning-profile");
  // The draft is null until the user edits something; until then the form shows
  // the server's copy, so a reload after saving always re-syncs without an effect.
  const [draft, setDraft] = useState<Form | null>(null);
  const [lesson, setLesson] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [lessonBusy, setLessonBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const data = profile.data;
  const form: Form = draft ?? (data
    ? { business_context: data.business_context, glossary: data.glossary, analysis_preferences: data.analysis_preferences, report_style: data.report_style }
    : EMPTY);
  const setForm = (next: Form) => setDraft(next);

  async function save(event: FormEvent) {
    event.preventDefault();
    setState("saving");
    setError(null);
    try {
      await api.put<LearningProfile>("/organisations/learning-profile", form);
      setDraft(null);
      profile.reload();
      setState("saved");
    } catch (caught) {
      setError((caught as Error).message);
      setState("idle");
    }
  }

  async function addLesson() {
    const text = lesson.trim();
    if (!text || lessonBusy) return;
    setLessonBusy(true);
    setError(null);
    try {
      await api.post<LearningProfile>("/organisations/learning-profile/lessons", { lesson: text });
      setLesson("");
      profile.reload();
    } catch (caught) {
      setError((caught as Error).message);
    }
    setLessonBusy(false);
  }

  function field(key: "business_context" | "glossary" | "analysis_preferences", label: string, hint: string, maxLength: number, placeholder: string) {
    return (
      <label className="field">
        <span>{label}</span>
        <textarea
          className="textarea"
          value={form[key]}
          maxLength={maxLength}
          disabled={!editable}
          placeholder={placeholder}
          onChange={(event) => { setForm({ ...form, [key]: event.target.value }); setState("idle"); }}
        />
        <small>{hint}</small>
      </label>
    );
  }

  return (
    <section className="card">
      <div className="card-head">
        <div className="row" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <div className="stat-icon" style={{ marginBottom: 0 }}><GraduationCap size={19} /></div>
          <div>
            <h2>Agent learning</h2>
            <p>Teach the agents about your business. They apply this guidance when planning analyses and wording reports.</p>
          </div>
        </div>
        {profile.data?.updated_at ? <span className="tiny muted">Updated {new Date(profile.data.updated_at).toLocaleDateString()}</span> : null}
      </div>

      {profile.loading && !profile.data ? (
        <Loading />
      ) : profile.error && !profile.data ? (
        <div className="card-pad"><Alert tone="error">{profile.error.message}</Alert></div>
      ) : (
        <form className="card-pad stack" onSubmit={save}>
          <Alert tone="info">
            This guidance shapes how the agents plan and explain — it never changes the data, the calculations or the verification checks. Every figure still comes from tested code.
          </Alert>
          {!editable ? <Alert tone="info">Only owners and admins can change the learning profile. You can read it below.</Alert> : null}
          {error ? <Alert tone="error">{error}</Alert> : null}

          {field(
            "business_context",
            "Business context",
            "What the business does, its branches, products, customers and seasonality. Up to 2,000 characters.",
            2000,
            "For example: We wholesale building materials in Zimbabwe, with branches in Harare and Bulawayo. Sales peak before the rainy season.",
          )}
          {field(
            "glossary",
            "Glossary",
            "What your column names and internal terms mean. Up to 3,000 characters.",
            3000,
            "For example: GP = gross profit. 'Ex-works' means collection from our warehouse. Branch codes: HRE = Harare, BYO = Bulawayo.",
          )}
          {field(
            "analysis_preferences",
            "Analysis preferences",
            "How you like analyses done: comparisons, segments, thresholds, what to highlight. Up to 2,000 characters.",
            2000,
            "For example: Always compare branches. Flag any product with a gross margin below 15%. Show month-on-month trends.",
          )}
          <label className="field">
            <span>Report style</span>
            <select
              className="select"
              value={form.report_style}
              disabled={!editable}
              onChange={(event) => { setForm({ ...form, report_style: event.target.value as ReportStyle }); setState("idle"); }}
            >
              {STYLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {editable ? (
            <div className="row">
              <button className="btn btn-primary" disabled={state === "saving"}>
                {state === "saving" ? "Saving…" : "Save learning profile"}
              </button>
              {state === "saved" ? <span className="small" style={{ color: "var(--success)", fontWeight: 600 }}>Saved — the agents will use this from the next analysis.</span> : null}
            </div>
          ) : null}

          <div className="stack-sm" style={{ borderTop: "1px solid var(--line)", paddingTop: 16 }}>
            <h3>Lessons from feedback</h3>
            <p className="small muted">Short, specific instructions captured from your team. The most recent 24 are kept and applied to future analyses.</p>
            {profile.data?.lessons.length ? (
              <ul className="bullets small">
                {profile.data.lessons.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : (
              <p className="small muted">No lessons yet. Rate an analysis on its results page, or add one below.</p>
            )}
            {canTeach ? (
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input
                  className="input"
                  value={lesson}
                  maxLength={500}
                  placeholder="For example: Always show amounts in USD and compare the same month last year."
                  onChange={(event) => setLesson(event.target.value)}
                />
                <button type="button" className="btn btn-secondary" onClick={() => void addLesson()} disabled={lessonBusy || !lesson.trim()}>
                  {lessonBusy ? "Adding…" : "Add lesson"}
                </button>
              </div>
            ) : null}
          </div>
        </form>
      )}
    </section>
  );
}
