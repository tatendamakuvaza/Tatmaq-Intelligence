"use client";

import { BarChart3, Bot, Database, FileText, LayoutDashboard, LogOut, Menu, Settings, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Brand, LogoMark } from "@/components/Logo";
import { useSession } from "@/services/session";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/analyst", label: "Analyst", icon: BarChart3 },
  { href: "/assistant", label: "AI assistant", icon: Sparkles },
  { href: "/datasets", label: "Datasets", icon: Database },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { profile, user, organisation, signOut } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="shell" data-menu={menuOpen ? "open" : "closed"}>
      <aside className="sidebar">
        <Brand />
        <nav className="nav" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} aria-current={pathname.startsWith(href) ? "page" : undefined} onClick={() => setMenuOpen(false)}>
              <Icon size={18} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="who">{profile?.full_name || user?.email}</div>
          <div className="where">{organisation?.name}</div>
          <button type="button" onClick={() => void signOut()}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>
      {/* Dims the page behind the open menu on small screens; a tap on it closes the menu. */}
      <div className="scrim" aria-hidden="true" onClick={() => setMenuOpen(false)} />
      <div className="shell-body">
        <div className="topbar">
          <button type="button" aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
            {menuOpen ? <X size={22} /> : <Menu size={22} />}
          </button>
          <div className="topbar-brand">
            <LogoMark size={26} /> TATMAQ Intelligence
          </div>
          {/* an empty third column, as wide as the menu button, keeps the name truly centred */}
          <span aria-hidden="true" />
        </div>
        <main className="main">
          <div className="page">{children}</div>
        </main>
      </div>
    </div>
  );
}
