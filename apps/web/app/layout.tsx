import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { SessionProvider } from "@/services/session";

import "./globals.css";

// Inter, served from this app (see app/fonts/OFL.txt for its licence). One variable file
// covers every weight, and its optical-size axis sharpens large headlines automatically.
const inter = localFont({
  src: "./fonts/Inter-latin-variable.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "TATMAQ Intelligence", template: "%s | TATMAQ Intelligence" },
  description: "Your AI analytics department: upload business data, ask a question, get verified analysis and a report.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f2440" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
