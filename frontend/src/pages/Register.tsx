import { useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Notice } from "../components/Notice";
import { RoleCards } from "../components/RoleCards";
import { homePathFor, type ConsoleRole } from "../lib/roles";
import { errorText } from "../lib/format";
import { useAuthStore } from "../store/auth";

// Judges and organizers need an invite code (enforced by the server, see
// backend/app/api/routes/auth.py). Participants register freely.

export default function Register() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);

  // An emailed judge invite links here with ?role=judge&code=..., pre-filling both.
  const params = new URLSearchParams(window.location.search);
  const linkRole = params.get("role");
  const [role, setRole] = useState<ConsoleRole>(linkRole === "judge" || linkRole === "organizer" ? linkRole : "participant");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState(params.get("code") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated && user) return <Navigate to={homePathFor(user.role)} replace />;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.register({
        name: name.trim(), email: email.trim(), password, role,
        ...(role !== "participant" ? { invite_code: inviteCode.trim() } : {}),
      });
      setSession(res.access_token, res.user);
      navigate(homePathFor(res.user.role), { replace: true });
    } catch (err) {
      setError(errorText(err, "Couldn't create your account. Try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="auth-inner">
        <div className="auth-head">
          <span className="chip chip--acid">NEW PLAYER</span>
          <h1>
            CREATE YOUR <em>ACCOUNT.</em>
          </h1>
          <p>Pick the role you're joining as. It's part of your account, so choose the one you'll actually use.</p>
        </div>

        <RoleCards value={role} onChange={setRole} />

        <form className="auth-form" onSubmit={handleSubmit}>
          <h2>Join as {role}</h2>
          <div className="field">
            <label htmlFor="name">Name</label>
            <input
              id="name"
              required
              autoComplete="name"
              maxLength={255}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ada Lovelace"
            />
          </div>
          <div className="field">
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              maxLength={72}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8–72 characters"
            />
            <span className="field-hint">At least 8 characters.</span>
          </div>
          {role !== "participant" ? (
            <div className="field">
              <label htmlFor="invite">Invite code</label>
              <input id="invite" required value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} placeholder="From an organizer" autoComplete="off" />
              <span className="field-hint">
                {role === "judge" ? "An organizer gives you a judge invite code." : "Organizer accounts need an invite code."}
              </span>
            </div>
          ) : null}
          {error ? <Notice kind="error">{error}</Notice> : null}
          <button className="btn btn--acid" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create account"} <ArrowRight size={17} />
          </button>
          <div className="auth-alt">
            <span>
              Already have one? <Link to="/login">Sign in</Link>
            </span>
            <Link to="/gallery">Browse the gallery</Link>
          </div>
        </form>

        <Link to="/" className="auth-back">
          <ArrowLeft size={14} /> BACK TO HOME
        </Link>
      </div>
    </main>
  );
}
