import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  activateAccount,
  getActiveOrganizationId,
  getCurrentUser,
  getHealth,
  login,
  logout,
  setActiveOrganizationId,
} from "../api/client";
import type { CurrentUser, HealthResponse } from "../types";

type AuthMode = HealthResponse["auth_mode"] | "loading";

interface AuthContextValue {
  mode: AuthMode;
  user: CurrentUser | null;
  activeOrganizationId: string;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  activate: (token: string, displayName: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  selectOrganization: (organizationId: string) => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function initialOrganization(user: CurrentUser): string {
  const customerMemberships = user.memberships.filter((item) => item.organization_slug !== "platform");
  const availableMemberships = customerMemberships.length > 0 ? customerMemberships : user.memberships;
  const saved = getActiveOrganizationId();
  if (saved && availableMemberships.some((item) => item.organization_id === saved)) {
    return saved;
  }
  const active = availableMemberships.find((item) => item.organization_id === user.active_organization_id);
  return active?.organization_id ?? availableMemberships[0]?.organization_id ?? "";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<AuthMode>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeOrganizationId, setActiveOrganization] = useState("");

  const applyUser = useCallback((value: CurrentUser) => {
    const organizationId = initialOrganization(value);
    setUser(value);
    setActiveOrganization(organizationId);
    setActiveOrganizationId(organizationId);
  }, []);

  const refreshUser = useCallback(async () => {
    const value = await getCurrentUser();
    applyUser(value);
  }, [applyUser]);

  useEffect(() => {
    let active = true;
    getHealth()
      .then(async (health) => {
        if (!active) return;
        setMode(health.auth_mode);
        if (health.auth_mode !== "accounts") return;
        try {
          const value = await getCurrentUser();
          if (active) applyUser(value);
        } catch {
          if (active) setUser(null);
        }
      })
      .catch(() => {
        if (active) setMode("legacy_token");
      });
    return () => {
      active = false;
    };
  }, [applyUser]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      applyUser(await login({ email, password }));
    },
    [applyUser],
  );

  const activate = useCallback(
    async (token: string, displayName: string, password: string) => {
      applyUser(await activateAccount({ token, display_name: displayName, password }));
    },
    [applyUser],
  );

  const signOut = useCallback(async () => {
    await logout();
    setUser(null);
    setActiveOrganization("");
    setActiveOrganizationId("");
  }, []);

  const selectOrganization = useCallback((organizationId: string) => {
    setActiveOrganization(organizationId);
    setActiveOrganizationId(organizationId);
    setUser((current) => current ? { ...current, active_organization_id: organizationId } : current);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      mode,
      user,
      activeOrganizationId,
      loading: mode === "loading",
      signIn,
      activate,
      signOut,
      selectOrganization,
      refreshUser,
    }),
    [mode, user, activeOrganizationId, signIn, activate, signOut, selectOrganization, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
