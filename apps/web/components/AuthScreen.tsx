"use client";

import { FileSpreadsheet, ShieldCheck, Sigma } from "lucide-react";
import type { ReactNode } from "react";

import { Brand } from "@/components/Logo";

const POINTS = [
  { icon: FileSpreadsheet, text: "Upload an Excel or CSV file. Five agents import it, clean it and tell you what they changed." },
  { icon: Sigma, text: "Every figure is calculated by tested code in exact decimal arithmetic, never guessed by an AI model." },
  { icon: ShieldCheck, text: "Results are reconciled before they are reported, and each one shows the formula and rows behind it." },
];

// Sign-in, sign-up and first-run screens share one centred column: the navy band with the
// brand and the promise, the form in a card across the band's lower edge, then the reasons.
export function AuthScreen({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <header className="auth-hero">
        <Brand size={36} />
        <p className="auth-headline">Your AI analytics department</p>
        <p className="tagline">One platform. Five collaborating agents. Verified answers and board-ready reports from your own business data.</p>
      </header>
      <main className="auth-card">{children}</main>
      <section className="auth-points" aria-label="Why TATMAQ Intelligence">
        {POINTS.map(({ icon: Icon, text }) => (
          <div key={text}>
            <Icon size={20} />
            <span>{text}</span>
          </div>
        ))}
      </section>
    </div>
  );
}
