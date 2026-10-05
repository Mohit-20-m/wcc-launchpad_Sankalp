import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "../store/auth";
import { consoleFor, homePathFor, type ConsoleRole } from "../lib/roles";

/**
 * Route guard. NOTE: this is a convenience for the person using the UI --
 * it stops them landing on a page that would only show errors. It is NOT
 * the security boundary: every API call is checked again by the backend
 * (`require_role`), so bypassing this guard gets an attacker nothing.
 */
export function RequireRole({ role, children }: { role: ConsoleRole; children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const location = useLocation();

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (consoleFor(user.role) !== role) {
    return <Navigate to={homePathFor(user.role)} replace />;
  }
  return <>{children}</>;
}
