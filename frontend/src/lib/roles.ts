import type { UserRole } from "../store/auth";

/** The three console roles the UI is organised around. */
export type ConsoleRole = "participant" | "judge" | "organizer";

/**
 * Map a backend role to the console it uses. `admin` shares the organizer
 * console (the backend grants admins organizer powers). `visitor` has no
 * console: it can only browse the public gallery.
 */
export function consoleFor(role: UserRole): ConsoleRole | null {
  switch (role) {
    case "participant":
      return "participant";
    case "judge":
      return "judge";
    case "organizer":
    case "admin":
      return "organizer";
    default:
      return null;
  }
}

export function homePathFor(role: UserRole): string {
  const c = consoleFor(role);
  return c ? `/${c}` : "/gallery";
}
