"use client";

import { Check, X } from "lucide-react";

import { formatDuration } from "@/lib/format";
import type { AgentTask } from "@/types/api";

// Shown before the Chief has written the plan, so the pipeline is visible from the first second.
const EXPECTED = [
  "Chief Intelligence Agent",
  "Data Acquisition Agent",
  "Data Cleaning Agent",
  "Statistical Analysis Agent",
  "Quality Verification",
  "Report Generation Agent",
];

export function AgentPipeline({ tasks, active }: { tasks: AgentTask[]; active: boolean }) {
  const steps = EXPECTED.map((name, index) => tasks.find((task) => task.sequence === index + 1) ?? name);
  // While the job is running, the first step not yet finished is the one in progress.
  const current = active ? steps.findIndex((step) => typeof step === "string" || !["completed", "failed"].includes(step.status)) : -1;

  return (
    <ol className="pipeline">
      {steps.map((step, index) => {
        const task = typeof step === "string" ? null : step;
        const status = task && task.status !== "pending" ? task.status : index === current ? "running" : "pending";
        return (
          <li key={index} className="step" data-status={status}>
            <div className="step-icon">
              {status === "completed" ? <Check size={16} /> : status === "failed" ? <X size={16} /> : status === "running" ? <span className="spinner" /> : index + 1}
            </div>
            <div>
              <div className="step-title">
                <strong>{task?.agent_name ?? (step as string)}</strong>
                {task ? <span className="tiny muted">{task.role}</span> : null}
                {task?.duration_ms != null && status === "completed" ? <span className="tiny muted num">{formatDuration(task.duration_ms)}</span> : null}
                {task && task.attempts > 1 ? <span className="badge badge-warning">{task.attempts} attempts</span> : null}
                {task?.model_name ? <span className="badge badge-info">AI: {task.model_name}</span> : null}
              </div>
              {task?.summary ? <p>{task.summary}</p> : null}
              {status === "running" && !task?.summary ? <p className="muted">Working...</p> : null}
              {task?.error_message ? <p style={{ color: "var(--danger)" }}>{task.error_message}</p> : null}
              {task && task.warnings.length > 0 && status === "completed" ? (
                <ul>
                  {task.warnings.slice(0, 4).map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                  {task.warnings.length > 4 ? <li>and {task.warnings.length - 4} more, listed with the results</li> : null}
                </ul>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
