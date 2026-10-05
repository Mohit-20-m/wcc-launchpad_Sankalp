import { useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Notice } from "../components/Notice";
import { RoleCards } from "../components/RoleCards";
import { consoleFor, homePathFor, type ConsoleRole } from "../lib/roles";
import { errorText } from "../lib/format";
import { useAuthStore } from "../store/auth";

export default function Login() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);

  const [role, setRole] = useState<ConsoleRole>("participant");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (isAuthenticated && user) return <Navigate to={homePathFor(user.role)} replace />;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setNote(null);
    setBusy(true);
    try {
      const res = await api.login({ email: email.trim(), password });
      const actual = consoleFor(res.user.role);

      // The SERVER decides what this account is. The card you picked is
      // only a check: if it doesn't match, we don't sign you in as
      // something you're not -- we point you at the right card instead.
      if (actual !== null && actual !== role) {
        setRole(actual);
        setNote(
          `That account is registered as ${actual.toUpperCase()}, not ${role.toUpperCase()}. ` +
            `We switched the card for you — press Continue to sign in.`
        );
        return;
      }

      setSession(res.access_token, res.user);
      navigate(homePathFor(res.user.role), { replace: true });
    } catch (err) {
      setError(errorText(err, "Couldn't sign you in. Try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="auth-inner">
        <div className="auth-head">
          <span className="chip chip--cyan">WCC LAUNCHPAD ACCESS</span>
          <h1>
            CHOOSE YOUR <em>STATION.</em>
          </h1>
          <p>
            One account system, three very different jobs. Pick the role you are signing in with — the platform will
            only ever show you what that role is allowed to see.
          </p>
        </div>

        <RoleCards value={role} onChange={setRole} />

        <form className="auth-form" onSubmit={handleSubmit}>
          <h2>Sign in as {role}</h2>
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          {error ? <Notice kind="error">{error}</Notice> : null}
          {note ? <Notice kind="info">{note}</Notice> : null}
          <button className="btn btn--acid" type="submit" disabled={busy}>
            {busy ? "Checking…" : "Continue"} <ArrowRight size={17} />
          </button>
          <div className="auth-alt">
            <span>
              No account yet? <Link to="/register">Create one</Link>
            </span>
            <button type="button" onClick={() => setNote("Forgot your password? Ask the event organizers to reset your account — self-service password reset isn't available yet.")}>
              Forgot password
            </button>
          </div>
        </form>

        <Link to="/" className="auth-back">
          <ArrowLeft size={14} /> BACK TO HOME
        </Link>
      </div>
    </main>
  );
}
