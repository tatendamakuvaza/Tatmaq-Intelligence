"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui";
import { api } from "@/services/api";
import type { JobFeedback } from "@/types/api";

type Rating = "helpful" | "not_helpful";

/**
 * Executive feedback on a completed analysis. The rating is always recorded;
 * an optional lesson is saved for the agents when the caller is an owner/admin.
 */
export function FeedbackCard({ jobId }: { jobId: string }) {
  const [rating, setRating] = useState<Rating | null>(null);
  const [lesson, setLesson] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<JobFeedback | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    if (!rating || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<JobFeedback>(`/analysis-jobs/${jobId}/feedback`, { rating, lesson: lesson.trim() || null });
      setDone(result);
    } catch (caught) {
      setError((caught as Error).message);
    }
    setBusy(false);
  }

  return (
    <section className="card card-pad stack-sm">
      <h3>Was this analysis useful?</h3>
      <p className="small muted">Your feedback is recorded, and owners and admins can turn it into a lesson the agents apply to future analyses.</p>
      {done ? (
        <Alert tone="success">
          Thank you — your feedback was recorded.
          {done.lesson_saved ? " The lesson was saved and the agents will apply it from the next analysis." : ""}
        </Alert>
      ) : (
        <>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div className="row">
            <button
              type="button"
              className={`btn btn-sm ${rating === "helpful" ? "btn-primary" : "btn-secondary"}`}
              aria-pressed={rating === "helpful"}
              onClick={() => setRating("helpful")}
            >
              <ThumbsUp size={14} /> Helpful
            </button>
            <button
              type="button"
              className={`btn btn-sm ${rating === "not_helpful" ? "btn-primary" : "btn-secondary"}`}
              aria-pressed={rating === "not_helpful"}
              onClick={() => setRating("not_helpful")}
            >
              <ThumbsDown size={14} /> Needs improvement
            </button>
          </div>
          {rating ? (
            <>
              <label className="field">
                <span>Optional: what should the agents do differently next time?</span>
                <textarea
                  className="textarea"
                  value={lesson}
                  maxLength={500}
                  placeholder="For example: Break the results down by branch, and flag margins below 15%."
                  onChange={(event) => setLesson(event.target.value)}
                />
                <small>Saved as a lesson for the agents when you are an owner or admin; otherwise only the rating is recorded.</small>
              </label>
              <div className="row">
                <button type="button" className="btn btn-primary btn-sm" onClick={() => void send()} disabled={busy}>
                  {busy ? "Sending…" : "Send feedback"}
                </button>
              </div>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
