import { Plus, Trash2 } from "lucide-react";
import type { RoundInput } from "../api/client";
import { inputToIso } from "../lib/format";

export interface RoundDraft {
  name: string;
  instructions: string;
  closes: string; // datetime-local value
  allow_idea: boolean;
  allow_repo: boolean;
  allow_video: boolean;
  allow_files: boolean;
  file_types: string; // comma separated
  max_file_mb: number;
  open_to_all: boolean;
}

export const newRoundDraft = (n: number): RoundDraft => ({
  name: `Round ${n}`,
  instructions: "",
  closes: "",
  allow_idea: true,
  allow_repo: true,
  allow_video: true,
  allow_files: true,
  file_types: "pdf,pptx,png,zip",
  max_file_mb: 25,
  open_to_all: n === 1,
});

/** Turn a draft into the API shape, or a message saying what's wrong. */
export function draftToInput(d: RoundDraft): RoundInput | string {
  const closes = inputToIso(d.closes);
  if (!d.name.trim()) return "Every round needs a name.";
  if (!closes) return `Set a deadline for "${d.name || "the round"}".`;
  return {
    name: d.name.trim(),
    ...(d.instructions.trim() ? { instructions: d.instructions.trim() } : {}),
    closes_at: closes,
    allow_idea: d.allow_idea,
    allow_repo: d.allow_repo,
    allow_video: d.allow_video,
    allow_files: d.allow_files,
    file_types: d.file_types.split(",").map((t) => t.trim()).filter(Boolean),
    max_file_mb: d.max_file_mb,
    open_to_all: d.open_to_all,
  };
}

interface Props {
  drafts: RoundDraft[];
  onChange: (next: RoundDraft[]) => void;
  /** Index offset so labels/ids stay unique when several builders exist. */
  idPrefix?: string;
  minRounds?: number;
  allowAdd?: boolean;
}

/** Define what teams may submit in each round: idea text, repo link,
 *  video link, files (with types and size), and who may enter. */
export function RoundsBuilder({ drafts, onChange, idPrefix = "rb", minRounds = 0, allowAdd = true }: Props) {
  const patch = (i: number, p: Partial<RoundDraft>) => onChange(drafts.map((d, j) => (j === i ? { ...d, ...p } : d)));
  return (
    <div className="stack">
      {drafts.map((d, i) => (
        <fieldset key={i} className="panel" style={{ margin: 0 }}>
          <legend className="chip chip--cyan">ROUND {i + 1}</legend>
          <div className="form-grid">
            <div className="field">
              <label htmlFor={`${idPrefix}-name-${i}`}>Round name</label>
              <input id={`${idPrefix}-name-${i}`} value={d.name} maxLength={255} onChange={(e) => patch(i, { name: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor={`${idPrefix}-close-${i}`}>Submissions close</label>
              <input id={`${idPrefix}-close-${i}`} type="datetime-local" value={d.closes} onChange={(e) => patch(i, { closes: e.target.value })} />
            </div>
            <div className="field span-2">
              <label htmlFor={`${idPrefix}-ins-${i}`}>What should teams do in this round?</label>
              <input id={`${idPrefix}-ins-${i}`} value={d.instructions} onChange={(e) => patch(i, { instructions: e.target.value })} placeholder="e.g. Ideas only: describe the problem and your approach." />
            </div>
            <div className="field span-2">
              <label>Teams may submit</label>
              <div className="check-grid">
                {(
                  [
                    ["allow_idea", "Idea text + tech stack"],
                    ["allow_repo", "Repository link"],
                    ["allow_video", "Video link"],
                    ["allow_files", "File uploads"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <input type="checkbox" checked={d[key]} onChange={(e) => patch(i, { [key]: e.target.checked })} /> {label}
                  </label>
                ))}
                {i > 0 ? (
                  <label>
                    <input type="checkbox" checked={!d.open_to_all} onChange={(e) => patch(i, { open_to_all: !e.target.checked })} /> Only teams I advance
                  </label>
                ) : null}
              </div>
            </div>
            {d.allow_files ? (
              <>
                <div className="field">
                  <label htmlFor={`${idPrefix}-types-${i}`}>Allowed file types</label>
                  <input id={`${idPrefix}-types-${i}`} value={d.file_types} onChange={(e) => patch(i, { file_types: e.target.value })} placeholder="pdf,pptx,png,zip" />
                </div>
                <div className="field">
                  <label htmlFor={`${idPrefix}-mb-${i}`}>Max size per file (MB, up to 50)</label>
                  <input id={`${idPrefix}-mb-${i}`} type="number" min={1} max={50} value={d.max_file_mb} onChange={(e) => patch(i, { max_file_mb: Number(e.target.value) })} />
                </div>
              </>
            ) : null}
          </div>
          {drafts.length > minRounds ? (
            <div className="row-actions" style={{ marginTop: 12 }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => onChange(drafts.filter((_, j) => j !== i))}>
                <Trash2 size={13} /> Remove round
              </button>
            </div>
          ) : null}
        </fieldset>
      ))}
      {allowAdd ? (
        <div>
          <button type="button" className="btn btn--cyan btn--sm" onClick={() => onChange([...drafts, newRoundDraft(drafts.length + 1)])}>
            <Plus size={14} /> Add a round
          </button>
        </div>
      ) : null}
    </div>
  );
}
