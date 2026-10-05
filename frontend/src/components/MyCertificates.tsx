import { useState } from "react";
import { Award, Copy, Download } from "lucide-react";
import { api, downloadCertificatePdf } from "../api/client";
import { errorText } from "../lib/format";
import { useLoad } from "../hooks/useLoad";
import { Notice } from "./Notice";

const KIND: Record<string, string> = { participation: "PARTICIPATION", winner: "WINNER", judge: "JUDGE" };

/** The signed-in person's own certificates: download the PDF or share a
 *  link anyone can use to check it's genuine. */
export function MyCertificates() {
  const q = useLoad(api.myCertificates, []);
  const [msg, setMsg] = useState<string | null>(null);
  const certs = q.data ?? [];
  const share = (code: string) => {
    const url = `${window.location.origin}/verify/${code}`;
    navigator.clipboard?.writeText(url).then(() => setMsg("Verification link copied."), () => setMsg(`Copy this link: ${url}`));
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Your certificates</h2>
          <p>Each has a code anyone can check at /verify, so it can't be faked.</p>
        </div>
        <Award size={18} />
      </div>
      {msg ? <Notice kind="info">{msg}</Notice> : null}
      {q.error ? <Notice kind="error">{q.error}</Notice> : null}
      {certs.length === 0 && !q.loading ? <div className="emptystate">No certificates yet. The organizers issue them after the event.</div> : null}
      <div className="rowlist">
        {certs.map((c) => (
          <div className="row" key={c.id}>
            <div className="row-main">
              <strong>{c.kind === "winner" ? `${c.title}${c.rank ? ` · rank ${c.rank}` : ""}` : c.kind === "judge" ? "Judge" : "Participant"} — {c.event_name}</strong>
              <span>{c.recipient_name} · code {c.code}</span>
            </div>
            <div className="row-side">
              <span className={`chip ${c.kind === "winner" ? "chip--acid" : "chip--cyan"}`}>{KIND[c.kind]}</span>
              <button type="button" className="btn btn--cyan btn--sm" onClick={() => downloadCertificatePdf(c.code).catch((e) => setMsg(errorText(e)))}>
                <Download size={13} /> PDF
              </button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => share(c.code)}>
                <Copy size={13} /> Share link
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
