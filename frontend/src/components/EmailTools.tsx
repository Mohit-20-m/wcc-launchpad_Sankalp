import { useEffect, useState } from "react";
import { Mail } from "lucide-react";
import { api, type MailPrefs } from "../api/client";
import { errorText } from "../lib/format";

/** Invite teammates by email (they get the code and a join link). */
export function InviteByEmail({ teamId, full }: { teamId: string; full: boolean }) {
  const [emails, setEmails] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    const list = emails.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
    if (!list.length) return setMsg({ ok: false, text: "Enter at least one email address." });
    setBusy(true);
    try {
      const r = await api.inviteTeamByEmail(teamId, list, note.trim() || undefined);
      setMsg({ ok: true, text: r.queued ? `Invite sent to ${r.queued} address(es).` : "Already invited in the last hour." });
      setEmails("");
      setNote("");
    } catch (err) {
      setMsg({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };
  if (full) return <p className="panel-note" style={{ marginTop: 14 }}>Your squad is full (4 members).</p>;
  return (
    <div className="field" style={{ marginTop: 18 }}>
      <label htmlFor="inv-emails">Invite by email</label>
      <input id="inv-emails" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="friend@college.edu, another@mail.com" />
      <input aria-label="Note (optional)" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Add a note (optional)" style={{ marginTop: 8 }} />
      <div className="row-actions" style={{ marginTop: 8 }}>
        <button className="btn btn--cyan btn--sm" type="button" disabled={busy} onClick={() => void send()}><Mail size={13} /> Send invite</button>
      </div>
      {msg ? <span className="field-hint" style={{ color: msg.ok ? undefined : "var(--coral, #ff6b6b)" }}>{msg.text}</span> : null}
      <span className="field-hint">They get your squad code and a link that fills it in for them.</span>
    </div>
  );
}

/** A person's own email choices. Invites, receipts and certificates always arrive. */
export function MailPreferences() {
  const [prefs, setPrefs] = useState<MailPrefs | null>(null);
  const [saved, setSaved] = useState("");
  useEffect(() => {
    api.myMailPrefs().then(setPrefs).catch(() => setPrefs({ reminders: true, updates: true }));
  }, []);
  const update = async (next: MailPrefs) => {
    setPrefs(next);
    try {
      await api.setMyMailPrefs(next);
      setSaved("Saved.");
    } catch (err) {
      setSaved(errorText(err));
    }
  };
  if (!prefs) return null;
  return (
    <section className="panel">
      <div className="panel-head"><div><h2>Email preferences</h2><p>Receipts, invites and certificates always arrive. The rest is up to you.</p></div><Mail size={18} /></div>
      <div className="stack" style={{ gap: 10 }}>
        <label><input type="checkbox" checked={prefs.reminders} onChange={(e) => void update({ ...prefs, reminders: e.target.checked })} /> Deadline reminders (only sent if your squad hasn't submitted)</label>
        <label><input type="checkbox" checked={prefs.updates} onChange={(e) => void update({ ...prefs, updates: e.target.checked })} /> Updates: teammates joining, results published</label>
        {saved ? <span className="field-hint">{saved}</span> : null}
      </div>
    </section>
  );
}
