"use client";

// Who is signed in, and which organisation and workspace they are working in.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { safeStorage } from "@/lib/storage";
import { api, setOrganisation, setUnauthorisedHandler } from "@/services/api";
import { auth, type AuthUser, type SignUpResult } from "@/services/auth";
import type { Organisation, Profile, Workspace } from "@/types/api";

type Status = "loading" | "signed_out" | "needs_organisation" | "ready" | "error";

type Session = {
  status: Status;
  error: string | null;
  user: AuthUser | null;
  profile: Profile | null;
  organisations: Organisation[];
  organisation: Organisation | null;
  workspaces: Workspace[];
  workspace: Workspace | null;
  can: (permission: string) => boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName: string) => Promise<SignUpResult>;
  signOut: () => Promise<void>;
  createOrganisation: (name: string) => Promise<void>;
  saveProfile: (fullName: string) => Promise<void>;
  selectOrganisation: (id: string) => Promise<void>;
  selectWorkspace: (id: string) => void;
  retry: () => void;
};

const SessionContext = createContext<Session | null>(null);
const ORG_KEY = "tatmaq:organisation";
const WORKSPACE_KEY = "tatmaq:workspace";

type State = Pick<Session, "status" | "error" | "user" | "profile" | "organisations" | "organisation" | "workspaces" | "workspace">;

const SIGNED_OUT: State = {
  status: "signed_out", error: null, user: null, profile: null, organisations: [], organisation: null, workspaces: [], workspace: null,
};

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ ...SIGNED_OUT, status: "loading" });

  const openOrganisation = useCallback(async (organisation: Organisation) => {
    setOrganisation(organisation.id);
    safeStorage.set(ORG_KEY, organisation.id);
    const workspaces = await api.get<Workspace[]>("/workspaces");
    const remembered = safeStorage.get(WORKSPACE_KEY);
    return { organisation, workspaces, workspace: workspaces.find((w) => w.id === remembered) ?? workspaces[0] ?? null };
  }, []);

  const bootstrap = useCallback(
    async (fullName?: string) => {
      const current = await auth.current();
      if (!current) {
        setOrganisation(null);
        setState(SIGNED_OUT);
        return;
      }
      try {
        // Creates the profile on first sign-in; a no-op afterwards.
        const profile = await api.post<Profile>("/auth/profile", fullName ? { full_name: fullName } : {});
        const organisations = await api.get<Organisation[]>("/organisations");
        if (organisations.length === 0) {
          setState({ ...SIGNED_OUT, status: "needs_organisation", user: current.user, profile });
          return;
        }
        const remembered = safeStorage.get(ORG_KEY);
        const opened = await openOrganisation(organisations.find((o) => o.id === remembered) ?? organisations[0]);
        setState({ status: "ready", error: null, user: current.user, profile, organisations, ...opened });
      } catch (error) {
        const current2 = await auth.current();
        if (!current2) return setState(SIGNED_OUT);
        setState((previous) => ({ ...previous, status: "error", error: (error as Error).message, user: current.user }));
      }
    },
    [openOrganisation],
  );

  useEffect(() => {
    setUnauthorisedHandler(() => {
      void auth.signOut().then(() => setState(SIGNED_OUT));
    });
    void bootstrap();
  }, [bootstrap]);

  const value = useMemo<Session>(
    () => ({
      ...state,
      can: (permission) => state.organisation?.permissions.includes(permission) ?? false,
      async signIn(email, password) {
        await auth.signIn(email, password);
        await bootstrap();
      },
      async signUp(email, password, fullName) {
        const result = await auth.signUp(email, password);
        if (result.session) await bootstrap(fullName);
        return result;
      },
      async signOut() {
        await auth.signOut();
        setOrganisation(null);
        setState(SIGNED_OUT);
      },
      async createOrganisation(name) {
        await api.post("/organisations", { name });
        await bootstrap();
      },
      async saveProfile(fullName) {
        const profile = await api.post<Profile>("/auth/profile", { full_name: fullName });
        setState((previous) => ({ ...previous, profile }));
      },
      async selectOrganisation(id) {
        const organisation = state.organisations.find((o) => o.id === id);
        if (!organisation) return;
        const opened = await openOrganisation(organisation);
        setState((previous) => ({ ...previous, ...opened }));
      },
      selectWorkspace(id) {
        const workspace = state.workspaces.find((w) => w.id === id) ?? null;
        if (workspace) safeStorage.set(WORKSPACE_KEY, workspace.id);
        setState((previous) => ({ ...previous, workspace }));
      },
      retry: () => {
        setState((previous) => ({ ...previous, status: "loading", error: null }));
        void bootstrap();
      },
    }),
    [state, bootstrap, openOrganisation],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside <SessionProvider>");
  return session;
}
