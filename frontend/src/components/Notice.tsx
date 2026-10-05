import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

type Kind = "error" | "ok" | "info" | "plain";

const STYLE: Record<Kind, string> = {
  error: "notice notice--coral",
  ok: "notice notice--acid",
  info: "notice notice--cyan",
  plain: "notice notice--cream",
};

/** Feedback banner in the design system's `.notice` style. */
export function Notice({ kind = "info", title, children }: { kind?: Kind; title?: string; children: ReactNode }) {
  const Icon = kind === "error" ? AlertTriangle : kind === "ok" ? CheckCircle2 : Info;
  return (
    <div className={STYLE[kind]} role={kind === "error" ? "alert" : "status"}>
      <Icon size={18} style={{ flex: "0 0 auto", marginTop: 1 }} />
      <div>
        {title ? <strong>{title}</strong> : null}
        {children}
      </div>
    </div>
  );
}
