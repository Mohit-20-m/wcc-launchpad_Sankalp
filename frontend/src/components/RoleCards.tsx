import { Check, Gamepad2, Scale, Shield } from "lucide-react";
import type { ConsoleRole } from "../lib/roles";

const ROLES = [
  {
    id: "participant" as const,
    icon: Gamepad2,
    title: "PARTICIPANT",
    blurb: "Team up, build a working product in 30 hours, and reach the finish line.",
    points: ["Form or join a team", "Submit before the deadline", "Vote in the public gallery"],
  },
  {
    id: "organizer" as const,
    icon: Shield,
    title: "ORGANIZER",
    blurb: "Full control of the event: setup, criteria, judges, results and records.",
    points: ["Create and configure events", "Weight the judging criteria", "Publish results and certificates"],
  },
  {
    id: "judge" as const,
    icon: Scale,
    title: "JUDGE",
    blurb: "Review only the submissions assigned to you, scored against defined criteria.",
    points: ["Private, isolated scoring", "Weighted criteria per event", "Written comments with every score"],
  },
];

/** The WCC Launchpad role cards, shared by sign-in and sign-up. */
export function RoleCards({ value, onChange }: { value: ConsoleRole; onChange: (r: ConsoleRole) => void }) {
  return (
    <div className="role-grid">
      {ROLES.map((item) => {
        const Icon = item.icon;
        const isActive = value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            aria-pressed={isActive}
            className={`role-card role-card--${item.id}`}
            onClick={() => onChange(item.id)}
          >
            {isActive ? (
              <span className="role-check">
                <Check size={14} strokeWidth={3} />
              </span>
            ) : null}
            <span className="role-icon">
              <Icon size={26} strokeWidth={2.4} />
            </span>
            <h3>{item.title}</h3>
            <p>{item.blurb}</p>
            <ul>
              {item.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </button>
        );
      })}
    </div>
  );
}
