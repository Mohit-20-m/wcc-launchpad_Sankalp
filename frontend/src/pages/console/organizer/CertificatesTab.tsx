import { useState } from "react";
import { Award, Download, Mail } from "lucide-react";
import { Link } from "react-router-dom";
import { api, downloadCertificatePdf, type EventOut } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { useLoad } from "../../../hooks/useLoad";
import { errorText, fmtDay } from "../../../lib/format";

interface Props {
  event: EventOut;
  flash: (kind: "ok" | "error", text: string) => void;
}

export function CertificatesTab({ event, flash }: Props) {
  const q = useLoad(() => api.eventCertificates(event.id), [event.id]);
  const [busy, setBusy] = useState(false);
  const [sendEmail, setSendEmail] = useState(true);
  const certs = q.data ?? [];
  const count = (k: string) => certs.filter((c) => c.kind === k && !c.revoked).length;
  const published = !!event.results_published_at;

  const issue = async (kinds: ("participation" | "winner" | "judge")[], label: string) => {
    setBusy(true);
    try {
      const r = await api.issueCertificates(event.id, kinds, sendEmail);
      flash("ok", r.total_issued === 0
        ? `Nothing new to issue for ${label} (${r.already_had} already issued).`
        : `Issued ${r.total_issued} ${label} certificate(s)${r.emailed ? `; emailing ${r.emailed} with the PDF attached` : ""}.`);
      q.reload();
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const emailOne = async (id: string) => {
    try {
      const r = await api.emailCertificate(event.id, id);
      flash("ok", `Certificate emailed to ${r.queued_to}.`);
    } catch (err) {
      flash("error", errorText(err));
    }
  };
  const revoke = async (id: string, name: string) => {
    if (!window.confirm(`Revoke ${name}'s certificate? Its verification page will say REVOKED.`)) return;
    try {
      await api.revokeCertificate(event.id, id);
      q.reload();
      flash("ok", "Certificate revoked.");
    } catch (err) {
      flash("error", errorText(err));
    }
  };

  return (
    <>
      <Notice kind="plain" title="Signed, verifiable certificates">
        Every certificate carries a code anyone can check at <code>/verify</code>, and a signature over its contents, so
        an edited name or prize stops verifying. Issuing is safe to repeat: nobody gets two.
      </Notice>
      <section className="panel">
        <div className="panel-head">
          <div><h2>Issue certificates</h2><p>Recipients see theirs on their own page and can download the PDF.</p></div>
          <Award size={18} />
        </div>
        <div className="grid-3">
          {([
            ["participation", "Participation", "Every member of a team that submitted a project."],
            ["winner", "Winners", published ? "Members of prize-winning teams." : "Publish results first."],
            ["judge", "Judges", "Judges who scored at least one project."],
          ] as const).map(([kind, label, help]) => (
            <div className="quest-card" key={kind}>
              <h3>{label.toUpperCase()}</h3>
              <p>{help}</p>
              <span className="chip chip--cyan">{count(kind)} ISSUED</span>
              <div className="row-actions" style={{ marginTop: 10 }}>
                <button className="btn btn--acid btn--sm" type="button" disabled={busy || (kind === "winner" && !published)} onClick={() => void issue([kind], label.toLowerCase())}>
                  Issue {label.toLowerCase()}
                </button>
              </div>
            </div>
          ))}
        </div>
        <label style={{ display: "block", marginTop: 14 }}>
          <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} /> Email each new certificate to its recipient, with the PDF attached
        </label>
        <div className="row-actions" style={{ marginTop: 14 }}>
          <button className="btn btn--cyan btn--sm" type="button" disabled={busy} onClick={() => void issue(published ? ["participation", "winner", "judge"] : ["participation", "judge"], "all available")}>
            Issue everything available
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><div><h2>Issued</h2><p>{certs.length} certificate(s) for this event.</p></div></div>
        {q.error ? <Notice kind="error">{q.error}</Notice> : null}
        {certs.length === 0 && !q.loading ? <div className="emptystate">None issued yet.</div> : (
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Recipient</th><th>Kind</th><th>Award</th><th>Code</th><th>Issued</th><th>Status</th><th /></tr></thead>
              <tbody>
                {certs.map((c) => (
                  <tr key={c.id}>
                    <td><strong>{c.recipient_name}</strong></td>
                    <td>{c.kind}</td>
                    <td>{c.kind === "winner" ? `${c.title}${c.rank ? ` (#${c.rank})` : ""}` : c.kind === "judge" ? "Judge" : "Participant"}</td>
                    <td><Link className="link-cyan" to={`/verify/${c.code}`}><code>{c.code}</code></Link></td>
                    <td>{fmtDay(c.issued_at)}</td>
                    <td>{c.revoked ? <span className="chip chip--ghost">REVOKED</span> : <span className="chip chip--acid">VALID</span>}</td>
                    <td>
                      {!c.revoked ? (
                        <span className="row-actions">
                          <button className="btn btn--ghost btn--sm" type="button" onClick={() => downloadCertificatePdf(c.code).catch((e) => flash("error", errorText(e)))}><Download size={12} /> PDF</button>
                          <button className="btn btn--ghost btn--sm" type="button" onClick={() => void emailOne(c.id)}><Mail size={12} /> Email</button>
                          <button className="btn btn--ghost btn--sm" type="button" onClick={() => void revoke(c.id, c.recipient_name)}>Revoke</button>
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
