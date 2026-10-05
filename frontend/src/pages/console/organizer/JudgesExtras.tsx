import { useState } from "react";
import { Copy } from "lucide-react";
import { api, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLive } from "../../../hooks/useLive";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtDay } from "../../../lib/format";

interface Props {
  event: EventOut;
  onChanged: () => void;
  flash: (kind: "ok" | "error", text: string) => void;
}

/** Judge invitations (invite codes) and declared conflicts of interest. */
export function JudgesExtras({ event, onChanged, flash }: Props) {
  const invitesQ = useLoad(api.invites, []);
  const conflictsQ = useLoad(() => api.conflicts(event.id), [event.id]);
  useLive(event.id, (t) => t.includes("conflicts") && conflictsQ.reload());
  const [label, setLabel] = useState("");
  const [uses, setUses] = useState(5);
  const [days, setDays] = useState(14);
  const [fresh, setFresh] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mailTo, setMailTo] = useState<Record<string, string>>({});
  const emailInvite = async (inviteId: string) => {
    const emails = (mailTo[inviteId] ?? "").split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
    if (emails.length === 0) return flash("error", "Enter at least one email address.");
    try {
      const r = await api.emailJudgeInvite(inviteId, emails);
      flash("ok", r.queued ? `Invite emailed to ${r.queued} judge(s).` : "Already emailed to those addresses.");
      setMailTo({ ...mailTo, [inviteId]: "" });
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  const create = async () => {
    setBusy(true);
    try {
      const inv = await api.createInvite({ role: "judge", max_uses: uses, expires_in_days: days, event_id: event.id, ...(label.trim() ? { label: label.trim() } : {}) });
      setFresh(inv.code);
      setLabel("");
      invitesQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const copy = (text: string) => navigator.clipboard?.writeText(text).catch(() => flash("error", `Couldn't copy. The code is ${text}`));
  const reassign = async (judgeId: string, projectId: string) => {
    try {
      await api.removeAssignment(judgeId, projectId);
      flash("ok", "Removed. Assign another judge from the form above.");
      conflictsQ.reload();
      onChanged();
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  const mine = (invitesQ.data ?? []).filter((i) => i.role === "judge");
  return (
    <>
      <section className="panel">
        <div className="panel-head"><div><h2>Invite judges</h2><p>Judges can't sign up without a code. Email a code straight to judges, or share it yourself; they enter it on the sign-up page.</p></div></div>
        <div className="form-grid">
          <div className="field"><label htmlFor="inv-label">Label (optional)</label><input id="inv-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Industry panel" /></div>
          <div className="field"><label htmlFor="inv-uses">Number of judges who can use it</label><input id="inv-uses" type="number" min={1} max={1000} value={uses} onChange={(e) => setUses(Number(e.target.value))} /></div>
          <div className="field"><label htmlFor="inv-days">Expires in (days)</label><input id="inv-days" type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} /></div>
        </div>
        <div className="row-actions" style={{ marginTop: 14 }}>
          <button className="btn btn--acid btn--sm" type="button" disabled={busy} onClick={create}>Create invite code</button>
        </div>
        {fresh ? (
          <div className="copy-box" style={{ marginTop: 14 }}>
            <span data-testid="new-invite">{fresh}</span>
            <button className="btn btn--ghost btn--sm" type="button" onClick={() => copy(fresh)}><Copy size={13} /> Copy</button>
          </div>
        ) : null}
        {mine.length > 0 ? (
          <div className="tablewrap" style={{ marginTop: 14 }}>
            <table className="data">
              <thead><tr><th>Label</th><th>Code</th><th>Used</th><th>Expires</th><th>Email it to</th><th /></tr></thead>
              <tbody>
                {mine.map((i) => (
                  <tr key={i.id}>
                    <td>{i.label ?? "—"}</td><td><code>{i.code}</code></td><td>{i.used_count} / {i.max_uses}</td>
                    <td>{i.revoked ? <span className="chip chip--ghost">REVOKED</span> : i.expires_at ? fmtDay(i.expires_at) : "never"}</td>
                    <td>
                      {!i.revoked ? (
                        <span className="row-actions">
                          <input aria-label="Judge emails" placeholder="judge@example.com, …" value={mailTo[i.id] ?? ""} onChange={(e) => setMailTo({ ...mailTo, [i.id]: e.target.value })} style={{ minWidth: 180 }} />
                          <button className="btn btn--cyan btn--sm" type="button" onClick={() => void emailInvite(i.id)}>Send</button>
                        </span>
                      ) : null}
                    </td>
                    <td>{!i.revoked ? <button className="btn btn--ghost btn--sm" type="button" onClick={() => api.revokeInvite(i.id).then(() => invitesQ.reload()).catch((e) => flash("error", errorText(e)))}>Revoke</button> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="panel-head"><div><h2>Declared conflicts of interest</h2><p>A judge who declares a conflict can't score or compare that project. Remove the assignment, then assign someone else.</p></div></div>
        {(conflictsQ.data ?? []).length === 0 ? <div className="emptystate">No conflicts declared.</div> : (
          <div className="rowlist">
            {(conflictsQ.data ?? []).map((c) => (
              <div className="row" key={`${c.judge_user_id}-${c.project_id}`}>
                <div className="row-main"><strong>{c.judge_name} → {c.project_title}</strong><span>{c.reason || "No reason given."}</span></div>
                <button className="btn btn--coral btn--sm" type="button" onClick={() => reassign(c.judge_user_id, c.project_id)}>Remove assignment</button>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
