import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BadgeCheck, Download, ShieldAlert } from "lucide-react";
import { api, downloadCertificatePdf, type VerifyOut } from "../api/client";
import { Notice } from "../components/Notice";
import { SiteTopbar } from "../components/SiteTopbar";
import { errorText, fmtDay } from "../lib/format";

const NAV = [
  { label: "Home", to: "/" },
  { label: "Gallery", to: "/gallery" },
];

/** Public certificate check. Anyone with the code can see who it was issued
 *  to and whether it's genuine, without signing in. */
export default function Verify() {
  const { code: param = "" } = useParams();
  const navigate = useNavigate();
  const [code, setCode] = useState(param);
  const [result, setResult] = useState<VerifyOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!param) return;
    setLoading(true);
    setError(null);
    setResult(null);
    api
      .verifyCertificate(param)
      .then(setResult)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [param]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (code.trim()) navigate(`/verify/${encodeURIComponent(code.trim())}`);
  };

  return (
    <div className="public-page">
      <SiteTopbar items={NAV} />
      <main className="public-main">
        <div>
          <span className="chip chip--cyan"><BadgeCheck size={12} /> CERTIFICATE CHECK</span>
        </div>
        <h1>
          IS IT
          <br />
          <em>REAL?</em>
        </h1>
        <form className="searchbar" onSubmit={submit}>
          <div className="field">
            <label htmlFor="cert-code">Certificate code</label>
            <input id="cert-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="XXXX-XXXX-XXXX" autoComplete="off" />
          </div>
          <button className="btn btn--acid" type="submit" style={{ alignSelf: "end" }}>Check</button>
        </form>

        {loading ? <div className="emptystate">Checking…</div> : null}
        {error ? <Notice kind="error" title="Not found">{error}</Notice> : null}
        {result ? (
          <section className="panel" aria-label="Certificate result">
            <div className="panel-head">
              <div>
                <h2>{result.valid ? "This certificate is genuine" : result.revoked ? "This certificate was revoked" : "This certificate FAILED verification"}</h2>
                <p>Code {result.code}, issued {fmtDay(result.issued_at)}.</p>
              </div>
              {result.valid ? <BadgeCheck size={28} /> : <ShieldAlert size={28} />}
            </div>
            <dl className="detail-grid">
              <dt>Awarded to</dt><dd><strong>{result.recipient_name}</strong></dd>
              <dt>Kind</dt><dd>{result.kind === "winner" ? `Winner: ${result.title}${result.rank ? ` (rank ${result.rank})` : ""}` : result.kind === "judge" ? "Judge" : "Participant"}</dd>
              <dt>Event</dt><dd>{result.event_name}</dd>
              {result.team_name ? (<><dt>Team</dt><dd>{result.team_name}</dd></>) : null}
              {result.project_title ? (<><dt>Project</dt><dd>{result.project_title}</dd></>) : null}
              <dt>Status</dt>
              <dd>
                <span className={`chip ${result.valid ? "chip--acid" : "chip--coral"}`}>
                  {result.valid ? "VALID" : result.revoked ? "REVOKED" : "NOT GENUINE"}
                </span>
              </dd>
            </dl>
            {result.valid ? (
              <div className="row-actions" style={{ marginTop: 14 }}>
                <button className="btn btn--cyan btn--sm" type="button" onClick={() => downloadCertificatePdf(result.code).catch((e) => setError(errorText(e)))}>
                  <Download size={13} /> Download PDF
                </button>
              </div>
            ) : null}
          </section>
        ) : null}
      </main>
    </div>
  );
}
