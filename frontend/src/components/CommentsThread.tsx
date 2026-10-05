import { useState, type FormEvent } from "react";
import { EyeOff, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Notice } from "./Notice";
import { useLoad } from "../hooks/useLoad";
import { errorText, fmtAgo } from "../lib/format";
import { useAuthStore } from "../store/auth";

/** Comments on a gallery project. Anyone can read; signed-in users can
 *  post (the server rate-limits); organizers see hide/unhide controls
 *  (the server only honours them for the event's own organizer). */
export function CommentsThread({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const user = useAuthStore((s) => s.user);
  const isOrganizer = user?.role === "organizer" || user?.role === "admin";
  const q = useLoad(() => api.comments(projectId), [projectId], { enabled: open });

  const post = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addComment(projectId, body);
      setBody("");
      q.reload();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const moderate = async (id: string, hidden: boolean) => {
    setError(null);
    try {
      await (hidden ? api.unhideComment(id) : api.hideComment(id));
      q.reload();
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <div className="comments">
      <button type="button" className="btn btn--ghost btn--sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <MessageSquare size={13} /> Comments{q.data ? ` (${q.data.filter((c) => !c.hidden).length})` : ""}
      </button>
      {open ? (
        <div className="stack" style={{ marginTop: 10, gap: 10 }}>
          {q.loading ? <span className="muted">Loading…</span> : null}
          {q.data && q.data.length === 0 ? <span className="muted">No comments yet.</span> : null}
          {(q.data ?? []).map((c) => (
            <div className="comment" key={c.id} style={c.hidden ? { opacity: 0.5 } : undefined}>
              <strong>{c.author_name}</strong> <span className="muted">· {fmtAgo(c.created_at)}{c.hidden ? " · hidden" : ""}</span>
              <p>{c.body}</p>
              {isOrganizer ? (
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => moderate(c.id, c.hidden)}>
                  <EyeOff size={12} /> {c.hidden ? "Unhide" : "Hide"}
                </button>
              ) : null}
            </div>
          ))}
          {error ? <Notice kind="error">{error}</Notice> : null}
          {user ? (
            <form className="stack" style={{ gap: 8 }} onSubmit={post}>
              <div className="field">
                <label htmlFor={`c-${projectId}`}>Add a comment</label>
                <textarea id={`c-${projectId}`} value={body} maxLength={1000} onChange={(e) => setBody(e.target.value)} required />
              </div>
              <button className="btn btn--cyan btn--sm" type="submit" disabled={busy || !body.trim()}>
                {busy ? "Posting…" : "Post comment"}
              </button>
            </form>
          ) : (
            <span className="muted">
              <Link to="/login" className="link-cyan">Sign in</Link> to comment.
            </span>
          )}
        </div>
      ) : null}
    </div>
  );
}
