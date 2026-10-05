import { create } from "zustand";
import { persist } from "zustand/middleware";

export type UserRole = "visitor" | "participant" | "judge" | "organizer" | "admin";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
  setSession: (token: string, user: AuthUser) => void;
  clearSession: () => void;
}

// Standard localStorage-backed persistence. The token is a signed JWT
// issued by our own backend; the server -- not this store -- is the
// authority on what the holder may do (see backend/app/core/security.py).
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      isAuthenticated: false,
      setSession: (token, user) => set({ token, user, isAuthenticated: true }),
      clearSession: () => set({ token: null, user: null, isAuthenticated: false }),
    }),
    { name: "launchpad-auth" }
  )
);
