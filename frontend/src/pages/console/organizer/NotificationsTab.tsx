import { useEffect, useState } from "react";
import { BellRing, Mail, RefreshCw, Send } from "lucide-react";
import { api, type EventOut, type MailSettingsIO, type OutboxRow } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtAgo } from "../../../lib/format";

interface Props {
  event: EventOut;
  flash: (kind: "ok" | "error", text: string) => void;
}

const KIND_LABEL: Record<string, string> = {
  team_created: "Team created",
  team_joined: "Teammate joined",
  team_invite: "Team invite",
  submission_receipt: "Submission receipt",
  judge_assigned: "Judge assigned",
  judge_assigned_batch: "Judge assignments",
  judge_invite: "Judge invite",
  scoring_open: "Scoring open",
  extension_granted: "Extension",
  deadline_reminder: "Deadline reminder",
  results_published: "Results out",
  certificate: "Certificate",
  welcome: "Welcome",
  test: "Test",
};
const STATUS_CHIP: Record<string, string> = { sent: "chip--acid", pending: "chip--cyan", failed: "chip--coral", skipped: "chip--ghost" };

/** Every email the platform sends for this event: what triggers them, the
 *  per-event switches, and a full delivery log with previews and retries. */
export function NotificationsTab({ event, flash }: Props) {
  const statusQ = useLoad(api.mailStatus, []);
  const settingsQ = useLoad(() => api.mailSettings(event.id), [event.id]);
  const [filter, setFilter] = useState("");
  const outboxQ = useLoad(() => api.outbox(event.id, filter || undefined), [event.id, filter], { pollMs: 5000 });
  const [draft, setDraft] = useState<MailSettingsIO | null>(null);
  const [preview, setPreview] = useState<OutboxRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [testTo, setTestTo] = useState("");

  useEffect(() => {
    if (settingsQ.data) setDraft(settingsQ.data);
  }, [settingsQ.data]);

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      const saved = await api.setMailSettings(event.id, draft);
      setDraft(saved);
      flash("ok", "Notification settings saved.");
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      flash("ok", await fn());
      outboxQ.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const open = async (id: string) => {
    try {
      setPreview(await api.outboxItem(event.id, id));
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  const st = statusQ.data;
  const counts = outboxQ.data?.counts;
  const emails = outboxQ.data?.emails ?? [];

  return (
    <>
      <Notice kind="plain" title="Notifications that send themselves">
        Teams get receipts, invites and deadline reminders; judges hear when work is assigned and when scoring opens;
        everyone hears when results are out; certificates arrive with the PDF attached. Each email is queued in the
        same database transaction as the action that caused it, so nobody is told about something that didn't happen,
        and nothing is lost if the mail server is down.
      </Notice>

      <div className="grid-side">
        <section className="panel">
          <div className="panel-head">
            <div><h2>Settings for this event</h2><p>Participants can also switch off reminders and updates for themselves.</p></div>
            <BellRing size={18} />
          </div>
          {draft ? (
            <div className="stack" style={{ gap: 12 }}>
              <label><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> Send emails for this event</label>
              <label><input type="checkbox" checked={draft.reminders_enabled} disabled={!draft.enabled} onChange={(e) => setDraft({ ...draft, reminders_enabled: e.target.checked })} /> Remind teams that haven't submitted</label>
              <div className="field">
                <label htmlFor="rem-hours">Reminder times (hours before the deadline)</label>
                <input id="rem-hours" value={draft.reminder_hours} disabled={!draft.enabled || !draft.reminders_enabled} onChange={(e) => setDraft({ ...draft, reminder_hours: e.target.value })} placeholder="24,3" />
                <span className="field-hint">Comma-separated. Only teams with no submission are reminded, once per time, using their own deadline if they have an extension.</span>
              </div>
              <label><input type="checkbox" checked={draft.certificate_emails} disabled={!draft.enabled} onChange={(e) => setDraft({ ...draft, certificate_emails: e.target.checked })} /> Email certificates when they're issued</label>
              <div className="row-actions">
                <button className="btn btn--acid btn--sm" type="button" disabled={busy} onClick={save}>Save settings</button>
              </div>
            </div>
          ) : <div className="emptystate">Loading…</div>}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div><h2>Delivery</h2><p>How this installation sends mail.</p></div>
            <Mail size={18} />
          </div>
          {st && !st.configured ? (
            <Notice kind="error" title="Email isn't set up yet">
              {st.problem} Emails are recorded below as skipped and can be retried once it's configured. Set{" "}
              <code>MAIL_PROVIDER</code> plus <code>SENDGRID_API_KEY</code> (or the <code>SMTP_*</code> settings) in{" "}
              <code>.env</code>, then restart the backend.
            </Notice>
          ) : null}
          {st ? (
            <div className="rowlist">
              <div className="row"><div className="row-main"><strong>Provider</strong><span>{st.provider === "sendgrid" ? "SendGrid API" : st.provider === "smtp" ? `SMTP${st.smtp ? ` (${st.smtp})` : ""}` : "Disabled: emails are logged, not sent"}{st.configured ? " · ready" : " · not configured"}</span></div></div>
              <div className="row"><div className="row-main"><strong>Sent from</strong><span>{st.from}</span></div></div>
              <div className="row"><div className="row-main"><strong>Links point to</strong><span>{st.links_point_to}</span></div></div>
              <div className="row"><div className="row-main"><strong>Never emailed</strong><span>demo and reserved addresses ({st.skipped_domains.join(", ")}, and *.example / *.test)</span></div></div>
            </div>
          ) : null}
          <div className="field" style={{ marginTop: 14 }}>
            <label htmlFor="test-to">Send a test email to</label>
            <input id="test-to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} placeholder="you@gmail.com" />
          </div>
          <div className="row-actions" style={{ marginTop: 10 }}>
            <button className="btn btn--cyan btn--sm" type="button" disabled={busy} onClick={() => void run(async () => {
              const r = await api.testEmail(event.id, testTo.trim() || undefined);
              return r.configured ? `Test email queued to ${r.queued_to}; it should arrive within a few seconds.` : `Recorded for ${r.queued_to}, but email isn't configured yet, so it wasn't sent.`;
            })}>
              <Send size={13} /> Send test
            </button>
            <button className="btn btn--ghost btn--sm" type="button" disabled={busy} onClick={() => void run(async () => {
              const r = await api.remindNow(event.id);
              return r.queued ? `Queued ${r.queued} reminder(s).` : "No reminders due right now (or everyone already got theirs).";
            })}>
              <BellRing size={13} /> Run reminder check now
            </button>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Outbox</h2>
            <p>
              {counts ? `${counts.sent} sent · ${counts.pending} waiting · ${counts.failed} failed · ${counts.skipped} skipped` : "Every email for this event."}
            </p>
          </div>
          <div className="row-side">
            <div className="field field--bar" style={{ margin: 0 }}>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by status">
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="pending">Waiting</option>
              <option value="failed">Failed</option>
              <option value="skipped">Skipped</option>
            </select>
            </div>
            <button className="btn btn--ghost btn--sm" type="button" onClick={() => outboxQ.reload()}><RefreshCw size={13} /></button>
          </div>
        </div>
        {outboxQ.error ? <Notice kind="error">{outboxQ.error}</Notice> : null}
        {emails.length === 0 && !outboxQ.loading ? <div className="emptystate">No emails yet. They appear here as teams form, submit and get judged.</div> : (
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>To</th><th>Type</th><th>Subject</th><th>Status</th><th>When</th><th /></tr></thead>
              <tbody>
                {emails.map((e) => (
                  <tr key={e.id}>
                    <td>{e.to_email}</td>
                    <td>{KIND_LABEL[e.kind] ?? e.kind}{e.has_attachment ? " 📎" : ""}</td>
                    <td>{e.subject}</td>
                    <td>
                      <span className={`chip ${STATUS_CHIP[e.status]}`} title={e.error ?? undefined}>{e.status.toUpperCase()}</span>
                      {e.status !== "sent" && e.error ? <span className="muted" style={{ display: "block", fontSize: 11 }}>{e.error}</span> : null}
                      {e.status === "pending" && e.attempts > 0 ? <span className="muted"> retry {e.attempts}</span> : null}
                    </td>
                    <td>{fmtAgo(e.sent_at ?? e.created_at)}</td>
                    <td>
                      <span className="row-actions">
                        <button className="btn btn--ghost btn--sm" type="button" onClick={() => void open(e.id)}>View</button>
                        {e.status === "failed" || e.status === "skipped" ? (
                          <button className="btn btn--ghost btn--sm" type="button" onClick={() => void run(async () => { await api.retryEmail(event.id, e.id); return "Queued again."; })}>Retry</button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {preview ? (
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="panel-head">
              <div><h2 style={{ fontSize: 18 }}>{preview.subject}</h2><p>To {preview.to_email}{preview.error ? ` · ${preview.error}` : ""}</p></div>
              <button className="btn btn--ghost btn--sm" type="button" onClick={() => setPreview(null)}>Close</button>
            </div>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit", lineHeight: 1.55 }}>{preview.body_text}</pre>
          </div>
        ) : null}
      </section>
    </>
  );
}
