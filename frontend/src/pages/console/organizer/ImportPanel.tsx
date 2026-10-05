import { useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { api, downloadImportTemplate, type EventOut, type ImportKind, type ImportResult } from "../../../api/client";
import { Notice } from "../../../components/Notice";
import { errorText } from "../../../lib/format";

interface Props {
  event: EventOut;
  flash: (kind: "ok" | "error", text: string) => void;
  onImported: () => void;
}

const HELP: Record<ImportKind, string> = {
  teams: "One row per team member: team_name, member_email, member_name. The first person listed leads the team.",
  projects: "One row per submission: team_name, title, summary, tech_stack, repo_url, video_url, track, round. Teams must exist first.",
  assignments: "One row per assignment: judge_email plus project_title and/or team_name. Judges must already have accounts.",
};

/** Bulk import with a preview: nothing is written until the organizer has
 *  seen every row's verdict and clicked Import. */
export function ImportPanel({ event, flash, onImported }: Props) {
  const [kind, setKind] = useState<ImportKind>("teams");
  const [file, setFile] = useState<File | null>(null);
  const [createAccounts, setCreateAccounts] = useState(false);
  const [skipErrors, setSkipErrors] = useState(false);
  const [checked, setChecked] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const run = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await api.importCsv(event.id, { kind, file, dry_run: dry, create_accounts: createAccounts, skip_errors: skipErrors });
      if (dry) {
        setChecked(r);
        setDone(null);
      } else {
        setDone(r);
        setChecked(null);
        setFile(null);
        if (input.current) input.current.value = "";
        flash("ok", `Imported ${r.created ?? 0} ${kind === "teams" ? "team(s)" : kind === "projects" ? "submission(s)" : "assignment(s)"}.`);
        onImported();
      }
    } catch (err) {
      flash("error", errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const reset = (next?: Partial<{ kind: ImportKind }>) => {
    setChecked(null);
    setDone(null);
    if (next?.kind) setKind(next.kind);
  };
  const credentialsCsv = () => {
    if (!done) return;
    const text = "email,name,temporary_password\n" + done.created_accounts.map((a) => `${a.email},"${a.name.replace(/"/g, '""')}",${a.temp_password}`).join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = "new-account-credentials.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  const canImport = !!checked && (checked.errors === 0 || skipErrors) && checked.ok > 0;
  const rows = checked ? (showAll ? checked.rows : checked.rows.filter((r) => r.status !== "ok")).slice(0, 200) : [];

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Bulk import</h2>
          <p>Bring in teams, submissions or judge assignments from a CSV. You'll see a row-by-row check before anything is saved.</p>
        </div>
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="imp-kind">What are you importing?</label>
          <select id="imp-kind" value={kind} onChange={(e) => reset({ kind: e.target.value as ImportKind })}>
            <option value="teams">Teams and members</option>
            <option value="projects">Submissions</option>
            <option value="assignments">Judge assignments</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="imp-file">CSV file</label>
          <input id="imp-file" ref={input} type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setChecked(null); setDone(null); }} />
        </div>
      </div>
      <p className="panel-note">{HELP[kind]}</p>
      <div className="check-grid" style={{ marginTop: 8 }}>
        {kind === "teams" ? (
          <label><input type="checkbox" checked={createAccounts} onChange={(e) => { setCreateAccounts(e.target.checked); setChecked(null); }} /> Create accounts for emails that don't have one (you'll get one-time passwords)</label>
        ) : null}
        <label><input type="checkbox" checked={skipErrors} onChange={(e) => setSkipErrors(e.target.checked)} /> Import only the valid rows if some have problems</label>
      </div>
      <div className="row-actions" style={{ marginTop: 14 }}>
        <button className="btn btn--ghost btn--sm" type="button" onClick={() => downloadImportTemplate(event.id, kind).catch((e) => flash("error", errorText(e)))}><Download size={13} /> Template</button>
        <button className="btn btn--cyan btn--sm" type="button" disabled={!file || busy} onClick={() => void run(true)}><Upload size={13} /> {busy && !checked ? "Checking…" : "Check file"}</button>
        <button className="btn btn--acid btn--sm" type="button" disabled={!canImport || busy} onClick={() => void run(false)}>Import {checked ? checked.ok : ""} row(s)</button>
      </div>

      {checked ? (
        <div className="stack" style={{ marginTop: 16 }}>
          <div className="row-actions">
            <span className="chip chip--acid">{checked.ok} OK</span>
            {checked.skipped ? <span className="chip chip--ghost">{checked.skipped} SKIPPED</span> : null}
            <span className={`chip ${checked.errors ? "chip--coral" : "chip--ghost"}`}>{checked.errors} PROBLEMS</span>
            <span className="muted">{checked.total} rows checked. Nothing has been saved yet.</span>
          </div>
          {checked.warnings.map((w) => <Notice key={w} kind="info">{w}</Notice>)}
          {checked.errors > 0 && !skipErrors ? <Notice kind="error" title="Fix the problems, or tick “import only the valid rows”.">Otherwise nothing is imported.</Notice> : null}
          {rows.length > 0 ? (
            <div className="tablewrap">
              <table className="data">
                <thead><tr><th>Line</th><th>Result</th><th>Detail</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.row}><td>{r.row}</td><td><span className={`chip ${r.status === "ok" ? "chip--acid" : r.status === "skip" ? "chip--ghost" : "chip--coral"}`}>{r.status.toUpperCase()}</span></td><td>{r.message || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <label className="muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show rows that are fine too</label>
        </div>
      ) : null}

      {done && done.created_accounts.length > 0 ? (
        <div className="stack" style={{ marginTop: 16 }}>
          <Notice kind="ok" title={`${done.created_accounts.length} account(s) created. Save these passwords now.`}>
            They are shown once. Give each person theirs; they can sign in right away.
          </Notice>
          <div className="tablewrap">
            <table className="data">
              <thead><tr><th>Email</th><th>Name</th><th>One-time password</th></tr></thead>
              <tbody>{done.created_accounts.map((a) => <tr key={a.email}><td>{a.email}</td><td>{a.name}</td><td><code>{a.temp_password}</code></td></tr>)}</tbody>
            </table>
          </div>
          <div><button className="btn btn--cyan btn--sm" type="button" onClick={credentialsCsv}><Download size={13} /> Download as CSV</button></div>
        </div>
      ) : null}
    </section>
  );
}
