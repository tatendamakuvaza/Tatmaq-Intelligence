"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useSession } from "@/services/session";

export default function Home() {
  const { status } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (status === "signed_out") router.replace("/login");
    else if (status !== "loading") router.replace("/dashboard");
  }, [status, router]);
  return (
    <div className="splash">
      <div className="spinner" aria-label="Loading" />
    </div>
  );
}
