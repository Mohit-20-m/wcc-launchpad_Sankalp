import { useState } from "react";
import { Download, FileText, Trash2 } from "lucide-react";
import { downloadProjectFile } from "../api/client";
import { errorText } from "../lib/format";
import { Notice } from "./Notice";

export interface FileLike {
  id: string;
  filename: string;
  size_bytes: number;
}

const size = (n: number) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** Files attached to a submission. Downloads go through the
 *  authenticated endpoint (the server decides who may open them). */
export function FileList({ projectId, files, onDelete }: { projectId: string; files: FileLike[]; onDelete?: (id: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  if (files.length === 0) return <span className="muted">No files attached.</span>;
  return (
    <div className="rowlist">
      {error ? <Notice kind="error">{error}</Notice> : null}
      {files.map((f) => (
        <div className="row" key={f.id}>
          <div className="row-main">
            <strong>
              <FileText size={13} style={{ verticalAlign: "-2px" }} /> {f.filename}
            </strong>
            <span>{size(f.size_bytes)}</span>
          </div>
          <div className="row-side">
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => downloadProjectFile(projectId, f).catch((e) => setError(errorText(e)))}
            >
              <Download size={13} /> Download
            </button>
            {onDelete ? (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => onDelete(f.id)} aria-label={`Delete ${f.filename}`}>
                <Trash2 size={13} />
              </button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}
