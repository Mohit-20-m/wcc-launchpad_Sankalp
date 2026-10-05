import { Link } from "react-router-dom";
import { LogOut } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export type ConsoleRole = "organizer" | "judge" | "participant";

export interface ConsoleNavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Feature not built yet: still navigable, but marked. */
  soon?: boolean;
}

interface ConsoleShellProps {
  role: ConsoleRole;
  roleLabel: string;
  userName: string;
  userMeta: string;
  nav: ConsoleNavItem[];
  active: string;
  onNavigate: (id: string) => void;
  onSignOut: () => void;
  title: string;
  subtitle: string;
  actions?: ReactNode;
  children: ReactNode;
}

/** The single shell shared by the organizer, judge and participant
 *  workspaces, in the WCC Launchpad design. */
export function ConsoleShell({
  role,
  roleLabel,
  userName,
  userMeta,
  nav,
  active,
  onNavigate,
  onSignOut,
  title,
  subtitle,
  actions,
  children,
}: ConsoleShellProps) {
  return (
    <div className="console-shell">
      <aside className="side">
        <Link to="/" className="side-brand">
          <span className="brand-mark">
            <span>W</span>
          </span>
          <b>WCC LAUNCHPAD</b>
        </Link>
        <div className={`side-role side-role--${role}`}>{roleLabel}</div>

        <nav className="side-nav" aria-label={`${roleLabel} sections`}>
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                aria-current={active === item.id}
                onClick={() => onNavigate(item.id)}
              >
                <Icon size={16} strokeWidth={2.4} />
                {item.label}
                {item.soon ? (
                  <span className="chip chip--soon" style={{ marginLeft: "auto" }}>
                    SOON
                  </span>
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="side-foot">
          <div className="side-user">
            <strong>{userName}</strong>
            <span>{userMeta}</span>
          </div>
          <button type="button" className="side-exit" onClick={onSignOut}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      <main className="console-main">
        <header className="console-bar">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          {actions ? <div className="bar-actions">{actions}</div> : null}
        </header>
        <div className="console-body">{children}</div>
      </main>
    </div>
  );
}
