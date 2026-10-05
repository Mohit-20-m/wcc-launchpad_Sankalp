// All requests go to a relative /api path, which Nginx proxies to the
// backend container. The browser never needs the backend's internal
// address. Auth is a Bearer token read from the auth store.

import { useAuthStore } from "../store/auth";
import type { AuthUser, UserRole } from "../store/auth";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Attach the stored token (default true). Off for login/register. */
  auth?: boolean;
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of {msg, loc}.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
    const msg = (first.msg ?? "Invalid input").replace(/^Value error, /, "");
    return field && field !== "body" ? `${field}: ${msg}` : msg;
  }
  return `Request failed with status ${status}`;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true } = opts;
  const token = auth ? useAuthStore.getState().token : null;

  const headers: Record<string, string> = {};
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  // (For FormData the browser sets the multipart Content-Type + boundary itself.)
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`/api${path}`, {
    method,
    headers,
    ...(body !== undefined ? { body: isForm ? (body as FormData) : JSON.stringify(body) } : {}),
  });

  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json())?.detail;
    } catch {
      // non-JSON error body: fall through to the generic message
    }
    // A rejected token means the session is over (expired or invalid):
    // drop it so route guards send the user back to sign in.
    if (res.status === 401 && token) useAuthStore.getState().clearSession();
    throw new ApiError(res.status, errorMessage(detail, res.status));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/* ------------------------------ types ------------------------------ */

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}
export interface Track {
  id: string;
  name: string;
}
export interface Prize {
  id: string;
  name: string;
  amount: number | null;
}
export type EventStatus = "upcoming" | "submissions_open" | "judging";
export type RoundState = "not_open" | "open" | "closed";
export interface RoundOut {
  id: string;
  event_id: string;
  number: number;
  name: string;
  instructions: string | null;
  opens_at: string | null;
  closes_at: string;
  closed_early_at: string | null;
  allow_idea: boolean;
  allow_repo: boolean;
  allow_video: boolean;
  allow_files: boolean;
  file_types: string[];
  max_file_mb: number;
  open_to_all: boolean;
  state: RoundState;
}
export interface RoundInput {
  name: string;
  instructions?: string;
  opens_at?: string;
  closes_at: string;
  allow_idea: boolean;
  allow_repo: boolean;
  allow_video: boolean;
  allow_files: boolean;
  file_types: string[];
  max_file_mb: number;
  open_to_all: boolean;
}
export interface EventOut {
  id: string;
  name: string;
  description: string | null;
  submissions_close: string;
  results_published_at: string | null;
  voting_mode: string;
  rounds: RoundOut[];
  starts_at: string | null;
  ends_at: string | null;
  capacity: number | null;
  status: EventStatus;
  tracks: Track[];
  prizes: Prize[];
}
export interface EventCreateInput {
  name: string;
  description?: string;
  submissions_close?: string;
  rounds?: RoundInput[];
  starts_at?: string;
  ends_at?: string;
  capacity?: number;
  tracks?: { name: string }[];
  prizes?: { name: string; amount?: number }[];
}
export interface Criterion {
  id: string;
  name: string;
  weight: number;
  description: string | null;
}
export interface CriterionInput {
  name: string;
  weight: number;
  description?: string;
}
export interface EventStats {
  teams: number;
  participants: number;
  submissions: number;
  judges_assigned: number;
  reviews_assigned: number;
  reviews_done: number;
}
export interface SubmissionRow {
  project_id: string;
  title: string;
  team_name: string;
  track_name: string | null;
  submitted_at: string | null;
  round_id: string | null;
  round_number: number | null;
  round_name: string | null;
  assigned: number;
  reviewed: number;
}
export interface ProgressRow {
  judge_user_id: string;
  judge_email: string;
  judge_name: string;
  assigned: number;
  completed: number;
}
export interface ResultRow {
  project_id: string;
  project_title: string;
  team_name: string;
  judge_count: number;
  raw_average: number;
  normalized_score: number;
}
export interface PairwiseRankRow {
  project_id: string;
  project_title: string;
  team_name: string;
  strength: number;
  comparisons: number;
}
export interface ProjectFile {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at?: string;
}
export interface ProjectOut {
  id: string;
  team_id: string;
  round_id: string | null;
  files: ProjectFile[];
  track_id: string | null;
  title: string;
  summary: string | null;
  repo_url: string | null;
  tech_stack: string | null;
  video_url: string | null;
  status: "draft" | "submitted" | "locked";
  submitted_at: string | null;
}
export interface ProjectPublic extends ProjectOut {
  team_name: string;
  track_name: string | null;
  event_id: string;
  event_name: string;
  round_number: number | null;
}
export interface ProjectInput {
  round_id?: string;
  title: string;
  summary?: string;
  repo_url?: string;
  tech_stack?: string;
  video_url?: string;
  /** null clears the track (an empty string would break the foreign key). */
  track_id?: string | null;
}
export interface TeamMember {
  user_id: string;
  name: string;
  is_leader: boolean;
}
export interface TeamRoundStatus {
  round_id: string;
  number: number;
  name: string;
  instructions: string | null;
  allow_idea: boolean;
  allow_repo: boolean;
  allow_video: boolean;
  allow_files: boolean;
  file_types: string[];
  max_file_mb: number;
  closes_at: string;
  state: RoundState;
  eligible: boolean;
  submission: ProjectOut | null;
}
export interface TeamMine {
  rounds: TeamRoundStatus[];
  current_round_id: string | null;
  id: string;
  name: string;
  invite_code: string;
  event_id: string;
  event_name: string;
  submissions_close: string;
  members: TeamMember[];
  project: ProjectOut | null;
}
export interface TeamOut {
  id: string;
  event_id: string;
  name: string;
  invite_code: string;
}
export interface QueueItem {
  project_id: string;
  project_title: string;
  project_summary: string | null;
  repo_url: string | null;
  tech_stack: string | null;
  video_url: string | null;
  team_name: string;
  track_name: string | null;
  event_id: string;
  event_name: string;
  scored: boolean;
  round_id: string | null;
  round_name: string | null;
  round_number: number | null;
  scorable: boolean;
  conflict: boolean;
  files: { id: string; filename: string; content_type: string; size_bytes: number }[];
}
export interface ScoreOut {
  id: string;
  judge_user_id: string;
  project_id: string;
  criteria: Record<string, number>;
  comment: string | null;
}
export interface JudgeOut {
  id: string;
  name: string;
  email: string;
}
export interface PairwisePair {
  project_a_id: string;
  project_a_title: string;
  project_b_id: string;
  project_b_title: string;
}
export interface Announcement {
  id: string;
  event_id: string | null;
  body: string;
  author_name: string;
  created_at: string;
}

export interface ExtensionOut {
  team_id: string;
  team_name: string;
  closes_at: string;
  reason: string | null;
}
export interface AdvancedOut {
  team_id: string;
  team_name: string;
}
export interface TeamRow {
  id: string;
  name: string;
  members: number;
  submitted_rounds: number;
}
export interface ConflictOut {
  judge_user_id: string;
  project_id: string;
  project_title: string;
  judge_name: string;
  judge_email: string;
  reason: string | null;
  created_at: string;
}
export interface AuditRow {
  id: string;
  actor_label: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: string | null;
  created_at: string;
}
export interface InviteOut {
  id: string;
  code: string;
  role: UserRole;
  label: string | null;
  event_id: string | null;
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  revoked: boolean;
  created_at: string;
}
export interface CommentOut {
  id: string;
  project_id: string;
  author_name: string;
  body: string;
  created_at: string;
  hidden: boolean;
}
export type VotingMode = "off" | "authenticated" | "email_gated" | "open_link";
export interface VotingConfig {
  mode: VotingMode;
  method: "single" | "quadratic";
  opens_at: string | null;
  closes_at: string | null;
  max_votes: number;
  credits: number;
  round_id: string | null;
  state: "off" | "not_open" | "open" | "closed";
  results_published: boolean;
}
export interface VotingConfigInput {
  mode: VotingMode;
  method: "single" | "quadratic";
  opens_at?: string;
  closes_at?: string;
  max_votes: number;
  credits: number;
  round_id?: string;
}
export interface BallotProject {
  id: string;
  title: string;
  summary: string | null;
  team_name: string;
  track_name: string | null;
  tech_stack: string | null;
  repo_url: string | null;
  video_url: string | null;
  my_votes: number;
}
export interface Ballot {
  config: VotingConfig;
  projects: BallotProject[];
  credits_used: number;
  can_vote: boolean;
  reason: string | null;
}
export interface VoteResultRow {
  project_id: string;
  project_title: string;
  team_name: string;
  votes: number;
  voters: number;
  rank: number;
}
export interface BallotAdminRow {
  voter_ref: string;
  kind: string;
  votes: number;
  credits: number;
  projects: number;
  ip_ref: string | null;
  shared_ip_voters: number;
  flagged: boolean;
  voided: boolean;
  updated_at: string;
}
export interface PublicResults {
  audit_anchor: { seq: number; hash: string } | null;
  event_id: string;
  event_name: string;
  published_at: string;
  round_name: string;
  judges_ranking: { rank: number; project_id: string; project_title: string; team_name: string; normalized_score: number; raw_average: number }[];
  winners: { prize_name: string; amount: number | null; rank: number; project_id: string; project_title: string; team_name: string }[];
  community: { rank: number; project_id: string; project_title: string; team_name: string; votes: number }[];
}

export interface ApiKeyOut {
  id: string;
  name: string;
  scope: "read" | "write";
  prefix: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked: boolean;
  key: string | null;
}
export interface WebhookOut {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret_hint: string;
  consecutive_failures: number;
  disabled_reason: string | null;
  created_at: string;
  secret: string | null;
}
export interface DeliveryOut {
  id: string;
  event_type: string;
  status: "pending" | "success" | "failed";
  attempts: number;
  response_code: number | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
  delivered_at: string | null;
  next_attempt_at: string | null;
  payload: string;
}
export interface CertOut {
  id: string;
  code: string;
  kind: "participation" | "winner" | "judge";
  title: string;
  recipient_name: string;
  event_id: string;
  event_name: string;
  team_name: string | null;
  project_title: string | null;
  rank: number | null;
  issued_at: string;
  revoked: boolean;
}
export interface VerifyOut {
  valid: boolean;
  revoked: boolean;
  genuine: boolean;
  code: string;
  kind: string;
  title: string;
  recipient_name: string;
  event_name: string;
  team_name: string | null;
  project_title: string | null;
  rank: number | null;
  issued_at: string;
}
export interface ImportRow {
  row: number;
  status: "ok" | "error" | "skip";
  message: string;
}
export interface ImportResult {
  kind: string;
  dry_run: boolean;
  total: number;
  ok: number;
  skipped: number;
  errors: number;
  committed: boolean;
  created?: number;
  rows: ImportRow[];
  warnings: string[];
  created_accounts: { email: string; name: string; temp_password: string }[];
}
export type ImportKind = "teams" | "projects" | "assignments";
export interface SimilarPair {
  kind: "duplicate_entry" | "possible_copy";
  score: number;
  reasons: string[];
  a: { project_id: string; title: string; team_name: string; round: number | null };
  b: { project_id: string; title: string; team_name: string; round: number | null };
}
export interface AuditVerify {
  ok: boolean;
  checked: number;
  head_seq: number;
  head_hash: string;
  problem: string | null;
  first_bad_seq: number | null;
}
export interface AuditAnchor {
  published: boolean;
  anchor_seq: number | null;
  anchor_hash: string | null;
  verified: boolean | null;
}

/* ------------------------------- calls ------------------------------ */


/* ---------------------------- Launchpad add-ons ---------------------------- */
export interface MailStatus {
  provider: string;
  configured: boolean;
  problem: string | null;
  from: string;
  smtp: string | null;
  skipped_domains: string[];
  github_token: boolean;
  links_point_to: string;
}
export interface MailSettingsIO {
  enabled: boolean;
  reminders_enabled: boolean;
  reminder_hours: string;
  certificate_emails: boolean;
}
export interface OutboxRow {
  id: string;
  to_email: string;
  kind: string;
  subject: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  error: string | null;
  created_at: string;
  sent_at: string | null;
  has_attachment: boolean;
  body_text?: string;
  body_html?: string;
}
export interface Outbox {
  counts: Record<"pending" | "sent" | "failed" | "skipped", number>;
  emails: OutboxRow[];
}
export interface MailPrefs {
  reminders: boolean;
  updates: boolean;
}
export interface ExpertiseJudge {
  id: string;
  name: string;
  email: string;
  track_ids: string[];
  load: number;
  in_event: boolean;
}
export interface Expertise {
  tracks: Track[];
  judges: ExpertiseJudge[];
}
export type TrackMode = "prefer" | "strict" | "ignore";
export interface AutoAssignInput {
  round_id?: string;
  judge_ids?: string[];
  reviews_per_project: number;
  max_per_judge?: number;
  track_mode: TrackMode;
  dry_run: boolean;
  notify?: boolean;
}
export interface AutoAssignResult {
  dry_run: boolean;
  round: { id: string; name: string } | null;
  assignments: { judge_user_id: string; judge_name: string; judge_email: string; project_id: string; project_title: string; track: string | null; track_match: boolean | null }[];
  judges: { judge_user_id: string; name: string; email: string; tracks: number; existing: number; new: number; total: number }[];
  summary: {
    projects: number;
    judges: number;
    reviews_per_project: number;
    reviews_needed: number;
    reviews_planned: number;
    capacity_per_judge: number;
    track_match_rate: number | null;
    load_min: number;
    load_max: number;
    projects_short: number;
  };
  short: { project_id: string; title: string; missing: number; reason: string }[];
  emails_queued?: number;
}
export type AnomalyKind = "flat" | "no_separation" | "bias" | "outlier" | "reversed" | "influence";
export interface AnomalyJudge {
  judge_user_id: string;
  name: string;
  email: string;
  reviews: number;
  mean: number;
  spread: number;
  mean_offset: number | null;
  agreement: number | null;
  influence: { max_rank_shift: number; changes_top3: boolean } | null;
  severity: number;
  flags: { kind: AnomalyKind; message: string; project_id?: string }[];
}
export interface AnomalyReport {
  round: { id: string; name: string } | null;
  judges: AnomalyJudge[];
  summary: { judges_analysed: number; judges_flagged: number; reviews: number; by_kind: Record<AnomalyKind, number>; top3_depends_on_judges: number };
  note: string;
}
export interface ScanFlag {
  kind: "pre_event_commits" | "post_deadline_commits" | "fork" | "few_commits";
  severity: "high" | "medium" | "info";
  message: string;
}
export interface ScanProject {
  project_id: string;
  title: string;
  team_name: string;
  repo_url: string | null;
  status: "done" | "pending" | "error" | "skipped" | "not_scanned";
  error: string | null;
  repo: string | null;
  files: number;
  commits: number | null;
  first_commit_at: string | null;
  last_commit_at: string | null;
  scanned_at: string | null;
  flags: ScanFlag[];
}
export interface CodePair {
  kind: "duplicate_entry" | "possible_copy";
  jaccard: number;
  containment: number;
  shared_fingerprints: number;
  a: { project_id: string; title: string; team_name: string; repo: string };
  b: { project_id: string; title: string; team_name: string; repo: string };
  files: { a: string; b: string; overlap: number }[];
}
export interface ScanReport {
  running: boolean;
  event_start: string | null;
  counts: Record<"done" | "pending" | "error" | "skipped" | "not_scanned", number>;
  flagged_projects: number;
  pairs: CodePair[];
  projects: ScanProject[];
  github_token: boolean;
}

/* ------------------------------ the client ------------------------------ */
export const api = {
  health: () => request<{ status: string; database: string }>("/health", { auth: false }),

  // auth
  login: (p: { email: string; password: string }) =>
    request<TokenResponse>("/auth/login", { method: "POST", body: p, auth: false }),
  register: (p: { email: string; name: string; password: string; role: UserRole; invite_code?: string }) =>
    request<TokenResponse>("/auth/register", { method: "POST", body: p, auth: false }),

  // events
  listEvents: () => request<EventOut[]>("/events", { auth: false }),
  createEvent: (p: EventCreateInput) => request<EventOut>("/events", { method: "POST", body: p }),
  getCriteria: (eventId: string) => request<Criterion[]>(`/events/${eventId}/criteria`, { auth: false }),
  setCriteria: (eventId: string, p: CriterionInput[]) =>
    request<Criterion[]>(`/events/${eventId}/criteria`, { method: "POST", body: p }),
  eventStats: (eventId: string) => request<EventStats>(`/events/${eventId}/stats`),
  eventSubmissions: (eventId: string, roundId?: string) =>
    request<SubmissionRow[]>(`/events/${eventId}/submissions${roundId ? `?round_id=${roundId}` : ""}`),
  eventProgress: (eventId: string) => request<ProgressRow[]>(`/events/${eventId}/progress`),
  eventResults: (eventId: string, roundId?: string) =>
    request<ResultRow[]>(`/events/${eventId}/results${roundId ? `?round_id=${roundId}` : ""}`),
  pairwiseResults: (eventId: string, roundId?: string) =>
    request<PairwiseRankRow[]>(`/events/${eventId}/pairwise-results${roundId ? `?round_id=${roundId}` : ""}`),

  // teams
  myTeams: () => request<TeamMine[]>("/teams/mine"),
  createTeam: (p: { event_id: string; name: string }) => request<TeamOut>("/teams", { method: "POST", body: p }),
  joinTeam: (invite_code: string) => request<TeamOut>("/teams/join", { method: "POST", body: { invite_code } }),

  // projects
  gallery: (params?: { q?: string; track_id?: string; event_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.event_id) qs.set("event_id", params.event_id);
    if (params?.q) qs.set("q", params.q);
    if (params?.track_id) qs.set("track_id", params.track_id);
    const s = qs.toString();
    return request<ProjectPublic[]>(`/projects${s ? `?${s}` : ""}`, { auth: false });
  },
  submitProject: (p: ProjectInput & { team_id: string }) =>
    request<ProjectOut>("/projects", { method: "POST", body: p }),
  updateProject: (id: string, p: Partial<ProjectInput>) =>
    request<ProjectOut>(`/projects/${id}`, { method: "PATCH", body: p }),

  // judging
  queue: () => request<QueueItem[]>("/judge/queue"),
  myScores: () => request<ScoreOut[]>("/judge/scores"),
  submitScore: (p: { project_id: string; criteria: Record<string, number>; comment?: string }) =>
    request<ScoreOut>("/judge/scores", { method: "POST", body: p }),
  listJudges: () => request<JudgeOut[]>("/judge/judges"),
  assignJudge: (p: { judge_email: string; project_id: string }) =>
    request<{ id: string }>("/judge/assignments", { method: "POST", body: p }),
  nextPair: () => request<PairwisePair>("/judge/pairwise/next"),
  submitComparison: (p: { project_a_id: string; project_b_id: string; winner_id: string }) =>
    request<{ status: string }>("/judge/pairwise", { method: "POST", body: p }),

  eventTeams: (eventId: string) => request<TeamRow[]>(`/events/${eventId}/teams`),
  // events managed by the caller (organizers: only their own)
  managedEvents: () => request<EventOut[]>("/events/managed"),

  // rounds
  addRound: (eventId: string, p: RoundInput) => request<RoundOut>(`/events/${eventId}/rounds`, { method: "POST", body: p }),
  updateRound: (eventId: string, roundId: string, p: Partial<RoundInput>) =>
    request<RoundOut>(`/events/${eventId}/rounds/${roundId}`, { method: "PATCH", body: p }),
  deleteRound: (eventId: string, roundId: string) => request<void>(`/events/${eventId}/rounds/${roundId}`, { method: "DELETE" }),
  closeSubmissions: (eventId: string, roundId: string) =>
    request<RoundOut>(`/events/${eventId}/rounds/${roundId}/close-submissions`, { method: "POST" }),
  extendRound: (eventId: string, roundId: string, p: { closes_at: string; reason?: string }) =>
    request<RoundOut>(`/events/${eventId}/rounds/${roundId}/extend`, { method: "POST", body: p }),
  extendTeam: (eventId: string, roundId: string, p: { team_id: string; closes_at: string; reason?: string }) =>
    request<ExtensionOut>(`/events/${eventId}/rounds/${roundId}/extend-team`, { method: "POST", body: p }),
  revokeTeamExtension: (eventId: string, roundId: string, teamId: string) =>
    request<void>(`/events/${eventId}/rounds/${roundId}/extend-team/${teamId}`, { method: "DELETE" }),
  listExtensions: (eventId: string, roundId: string) => request<ExtensionOut[]>(`/events/${eventId}/rounds/${roundId}/extensions`),
  listAdvanced: (eventId: string, roundId: string) => request<AdvancedOut[]>(`/events/${eventId}/rounds/${roundId}/advanced`),
  advanceTeams: (eventId: string, roundId: string, team_ids: string[]) =>
    request<AdvancedOut[]>(`/events/${eventId}/rounds/${roundId}/advance`, { method: "POST", body: { team_ids } }),
  advanceTop: (eventId: string, roundId: string, top_n: number) =>
    request<AdvancedOut[]>(`/events/${eventId}/rounds/${roundId}/advance-top`, { method: "POST", body: { top_n } }),

  // project files
  uploadFile: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ProjectFile>(`/projects/${projectId}/files`, { method: "POST", body: form });
  },
  deleteFile: (projectId: string, fileId: string) => request<void>(`/projects/${projectId}/files/${fileId}`, { method: "DELETE" }),

  // judging extras
  declareConflict: (project_id: string, reason?: string) =>
    request<{ status: string }>("/judge/conflicts", { method: "POST", body: { project_id, ...(reason ? { reason } : {}) } }),
  removeAssignment: (judgeUserId: string, projectId: string) =>
    request<void>(`/judge/assignments/${judgeUserId}/${projectId}`, { method: "DELETE" }),
  conflicts: (eventId: string) => request<ConflictOut[]>(`/events/${eventId}/conflicts`),

  // voting
  votingConfig: (eventId: string) => request<VotingConfig>(`/voting/${eventId}/config`, { auth: false }),
  setVotingConfig: (eventId: string, p: VotingConfigInput) => request<VotingConfig>(`/voting/${eventId}/config`, { method: "PUT", body: p }),
  ballot: (eventId: string, params: { email?: string; voter_token?: string }) => {
    const qs = new URLSearchParams();
    if (params.email) qs.set("email", params.email);
    if (params.voter_token) qs.set("voter_token", params.voter_token);
    const q = qs.toString();
    return request<Ballot>(`/voting/${eventId}/ballot${q ? `?${q}` : ""}`);
  },
  putBallot: (eventId: string, p: { allocations: { project_id: string; votes: number }[]; email?: string; voter_token?: string }) =>
    request<Ballot>(`/voting/${eventId}/ballot`, { method: "PUT", body: p }),
  allowlist: (eventId: string) => request<{ patterns: string[] }>(`/voting/${eventId}/allowlist`),
  setAllowlist: (eventId: string, patterns: string[]) =>
    request<{ patterns: string[] }>(`/voting/${eventId}/allowlist`, { method: "PUT", body: { patterns } }),
  voteResults: (eventId: string) => request<VoteResultRow[]>(`/voting/${eventId}/results`),
  ballots: (eventId: string) => request<BallotAdminRow[]>(`/voting/${eventId}/ballots`),
  voidBallot: (eventId: string, ref: string) => request<void>(`/voting/${eventId}/ballots/${encodeURIComponent(ref)}/void`, { method: "POST" }),
  restoreBallot: (eventId: string, ref: string) => request<void>(`/voting/${eventId}/ballots/${encodeURIComponent(ref)}/restore`, { method: "POST" }),

  // comments
  comments: (projectId: string) => request<CommentOut[]>(`/projects/${projectId}/comments`),
  addComment: (projectId: string, body: string) => request<CommentOut>(`/projects/${projectId}/comments`, { method: "POST", body: { body } }),
  hideComment: (id: string) => request<void>(`/comments/${id}/hide`, { method: "POST" }),
  unhideComment: (id: string) => request<void>(`/comments/${id}/unhide`, { method: "POST" }),

  // results publishing
  publishResults: (eventId: string, round_id?: string) =>
    request<PublicResults>(`/events/${eventId}/publish-results`, { method: "POST", body: round_id ? { round_id } : {} }),
  unpublishResults: (eventId: string) => request<void>(`/events/${eventId}/unpublish-results`, { method: "POST" }),
  publicResults: (eventId: string) => request<PublicResults>(`/events/${eventId}/public-results`, { auth: false }),

  // audit + invites
  audit: (eventId: string, action?: string) =>
    request<AuditRow[]>(`/events/${eventId}/audit?limit=300${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  createInvite: (p: { role: UserRole; label?: string; max_uses: number; expires_in_days: number; event_id?: string }) =>
    request<InviteOut>("/invites", { method: "POST", body: p }),
  invites: () => request<InviteOut[]>("/invites"),
  revokeInvite: (id: string) => request<InviteOut>(`/invites/${id}`, { method: "DELETE" }),

  // Platform: API keys, webhooks
  apiKeys: (eventId: string) => request<ApiKeyOut[]>(`/events/${eventId}/api-keys`),
  createApiKey: (eventId: string, p: { name: string; scope: "read" | "write"; expires_in_days?: number }) =>
    request<ApiKeyOut>(`/events/${eventId}/api-keys`, { method: "POST", body: p }),
  revokeApiKey: (eventId: string, id: string) => request<ApiKeyOut>(`/events/${eventId}/api-keys/${id}`, { method: "DELETE" }),
  webhookEventTypes: () => request<string[]>("/webhook-event-types", { auth: false }),
  webhooks: (eventId: string) => request<WebhookOut[]>(`/events/${eventId}/webhooks`),
  createWebhook: (eventId: string, p: { url: string; events: string[] }) =>
    request<WebhookOut>(`/events/${eventId}/webhooks`, { method: "POST", body: p }),
  patchWebhook: (eventId: string, id: string, p: { url?: string; events?: string[]; active?: boolean }) =>
    request<WebhookOut>(`/events/${eventId}/webhooks/${id}`, { method: "PATCH", body: p }),
  deleteWebhook: (eventId: string, id: string) => request<void>(`/events/${eventId}/webhooks/${id}`, { method: "DELETE" }),
  rotateWebhookSecret: (eventId: string, id: string) => request<WebhookOut>(`/events/${eventId}/webhooks/${id}/rotate-secret`, { method: "POST" }),
  testWebhook: (eventId: string, id: string) => request<DeliveryOut>(`/events/${eventId}/webhooks/${id}/test`, { method: "POST" }),
  webhookDeliveries: (eventId: string, id: string) => request<DeliveryOut[]>(`/events/${eventId}/webhooks/${id}/deliveries`),
  retryDelivery: (eventId: string, id: string, deliveryId: string) =>
    request<DeliveryOut>(`/events/${eventId}/webhooks/${id}/deliveries/${deliveryId}/retry`, { method: "POST" }),

  // Platform: certificates
  issueCertificates: (eventId: string, kinds: ("participation" | "winner" | "judge")[], send_email = true) =>
    request<{ issued: Record<string, number>; total_issued: number; already_had: number; emailed: number }>(`/events/${eventId}/certificates/issue`, { method: "POST", body: { kinds, send_email } }),
  eventCertificates: (eventId: string) => request<CertOut[]>(`/events/${eventId}/certificates`),
  revokeCertificate: (eventId: string, id: string) => request<CertOut>(`/events/${eventId}/certificates/${id}/revoke`, { method: "POST" }),
  myCertificates: () => request<CertOut[]>("/certificates/mine"),
  verifyCertificate: (code: string) => request<VerifyOut>(`/certificates/verify/${encodeURIComponent(code)}`, { auth: false }),

  // Platform: bulk import + integrity
  importCsv: (eventId: string, p: { kind: ImportKind; file: File; dry_run: boolean; create_accounts: boolean; skip_errors: boolean }) => {
    const form = new FormData();
    form.append("kind", p.kind);
    form.append("dry_run", String(p.dry_run));
    form.append("create_accounts", String(p.create_accounts));
    form.append("skip_errors", String(p.skip_errors));
    form.append("file", p.file);
    return request<ImportResult>(`/events/${eventId}/import`, { method: "POST", body: form });
  },
  similarity: (eventId: string) => request<{ pairs: SimilarPair[]; duplicate_entries: number; possible_copies: number }>(`/events/${eventId}/similarity`),
  auditVerify: (eventId: string) => request<AuditVerify>(`/events/${eventId}/audit/verify`),
  auditAnchor: (eventId: string) => request<AuditAnchor>(`/events/${eventId}/audit/anchor`, { auth: false }),


  // Launchpad: notifications
  mailStatus: () => request<MailStatus>("/mail/status"),
  mailSettings: (eventId: string) => request<MailSettingsIO>(`/events/${eventId}/mail/settings`),
  setMailSettings: (eventId: string, p: MailSettingsIO) => request<MailSettingsIO>(`/events/${eventId}/mail/settings`, { method: "PUT", body: p }),
  outbox: (eventId: string, status?: string) => request<Outbox>(`/events/${eventId}/mail/outbox${status ? `?status_filter=${status}` : ""}`),
  outboxItem: (eventId: string, id: string) => request<OutboxRow>(`/events/${eventId}/mail/outbox/${id}`),
  retryEmail: (eventId: string, id: string) => request<OutboxRow>(`/events/${eventId}/mail/outbox/${id}/retry`, { method: "POST" }),
  testEmail: (eventId: string, to?: string) =>
    request<{ queued_to: string; configured: boolean }>(`/events/${eventId}/mail/test`, { method: "POST", body: to ? { to } : {} }),
  remindNow: (eventId: string) => request<{ queued: number }>(`/events/${eventId}/mail/remind-now`, { method: "POST" }),
  myMailPrefs: () => request<MailPrefs>("/me/mail-preferences"),
  setMyMailPrefs: (p: MailPrefs) => request<MailPrefs>("/me/mail-preferences", { method: "PUT", body: p }),
  inviteTeamByEmail: (teamId: string, emails: string[], note?: string) =>
    request<{ queued: number }>(`/teams/${teamId}/invite-email`, { method: "POST", body: { emails, ...(note ? { note } : {}) } }),
  emailJudgeInvite: (inviteId: string, emails: string[]) => request<{ queued: number }>(`/invites/${inviteId}/email`, { method: "POST", body: { emails } }),
  emailCertificate: (eventId: string, certId: string) => request<{ queued_to: string }>(`/events/${eventId}/certificates/${certId}/email`, { method: "POST" }),

  // Launchpad: assignment, anomalies, code scan
  expertise: (eventId: string) => request<Expertise>(`/events/${eventId}/expertise`),
  setExpertise: (eventId: string, judgeId: string, track_ids: string[]) =>
    request<{ judge_user_id: string; track_ids: string[] }>(`/events/${eventId}/expertise/${judgeId}`, { method: "PUT", body: { track_ids } }),
  autoAssign: (eventId: string, p: AutoAssignInput) => request<AutoAssignResult>(`/events/${eventId}/auto-assign`, { method: "POST", body: p }),
  anomalies: (eventId: string, roundId?: string) => request<AnomalyReport>(`/events/${eventId}/anomalies${roundId ? `?round_id=${roundId}` : ""}`),
  startCodeScan: (eventId: string, force = false) => request<{ started: boolean; projects: number }>(`/events/${eventId}/code-scan`, { method: "POST", body: { force } }),
  codeScan: (eventId: string) => request<ScanReport>(`/events/${eventId}/code-scan`),

  // announcements
  announcements: (eventId?: string) =>
    request<Announcement[]>(`/announcements${eventId ? `?event_id=${encodeURIComponent(eventId)}` : ""}`, {
      auth: false,
    }),
  postAnnouncement: (p: { event_id?: string; body: string }) =>
    request<Announcement>("/announcements", { method: "POST", body: p }),
};

/** Fetch an authenticated file and hand it to the browser as a download.
 *  A plain link can't carry the Bearer token, so we fetch a blob. */
async function downloadBlob(path: string, fallbackName: string, forbidden = "You don't have access to this."): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    if (res.status === 401) useAuthStore.getState().clearSession();
    throw new ApiError(res.status, res.status === 403 ? forbidden : "Download failed.");
  }
  const disposition = res.headers.get("content-disposition") ?? "";
  const name = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = decodeURIComponent(name);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Scores CSV for ONE event (the server refuses events you don't own). */
export const downloadScoresCsv = (eventId: string) =>
  downloadBlob(`/export.csv?event_id=${encodeURIComponent(eventId)}`, "launchpad-scores.csv", "You can only export events you created.");
export const downloadAuditCsv = (eventId: string) => downloadBlob(`/events/${eventId}/audit.csv`, "audit-log.csv");
export const downloadProjectFile = (projectId: string, file: { id: string; filename: string }) =>
  downloadBlob(`/projects/${projectId}/files/${file.id}`, file.filename, "You don't have access to this file.");

export const downloadCertificatePdf = (code: string) => downloadBlob(`/certificates/${encodeURIComponent(code)}/pdf`, `certificate-${code}.pdf`, "This certificate is no longer valid.");
export const downloadImportTemplate = (eventId: string, kind: ImportKind) => downloadBlob(`/events/${eventId}/import/template?kind=${kind}`, `import-${kind}-template.csv`);
export const downloadEventExport = (eventId: string, file: "projects.csv" | "teams.csv" | "bundle.json") =>
  downloadBlob(`/events/${eventId}/export/${file}`, file, "You can only export events you created.");
