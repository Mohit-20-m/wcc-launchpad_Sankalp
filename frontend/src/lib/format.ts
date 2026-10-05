/** Small, dependency-free formatting helpers. All times shown in UTC so
 *  they match the server's deadline clock and the "UTC" labels. */

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${MONTHS[d.getUTCMonth()]} ${String(d.getUTCDate()).padStart(2, "0")}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${hh}:${mm} UTC`;
}

export function fmtAgo(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

export interface TimeLeft {
  expired: boolean;
  days: number;
  hours: number;
  minutes: number;
}

export function timeLeft(iso: string | null | undefined, now: number): TimeLeft {
  if (!iso) return { expired: true, days: 0, hours: 0, minutes: 0 };
  const ms = new Date(iso).getTime() - now;
  if (Number.isNaN(ms) || ms <= 0) return { expired: true, days: 0, hours: 0, minutes: 0 };
  const minutesTotal = Math.floor(ms / 60000);
  return {
    expired: false,
    days: Math.floor(minutesTotal / 1440),
    hours: Math.floor((minutesTotal % 1440) / 60),
    minutes: minutesTotal % 60,
  };
}

export function isPast(iso: string | null | undefined, now = Date.now()): boolean {
  return !!iso && new Date(iso).getTime() <= now;
}

/** "$2,500" (table) or "$2.5K" (compact, for cards). */
export function money(total: number, compact = false): string {
  if (compact && total >= 1000) {
    const k = total / 1000;
    return `$${Number.isInteger(k) ? k : k.toFixed(1)}K`;
  }
  return `$${total.toLocaleString("en-US")}`;
}

export function initials(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "??";
  if (words.length === 1) return words[0]!.slice(0, 2).toUpperCase();
  return (words[0]![0]! + words[1]![0]!).toUpperCase();
}

export function truncate(text: string | null | undefined, max: number): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

export function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 8) : id;
}

export function errorText(err: unknown, fallback = "Something went wrong. Try again."): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** <input type="date|datetime-local"> value -> ISO string (or undefined). */
export function inputToIso(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined;
  const withTime = value.length === 10 ? `${value}T${endOfDay ? "23:59" : "00:00"}` : value;
  const d = new Date(withTime);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export const EVENT_STATUS_LABEL: Record<string, string> = {
  upcoming: "UPCOMING",
  submissions_open: "SUBMISSIONS OPEN",
  judging: "JUDGING",
};
