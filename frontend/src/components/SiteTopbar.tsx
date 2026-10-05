import { useState } from "react";
import { Link } from "react-router-dom";
import { Gamepad2, Menu, Rocket, Volume2, VolumeX, X } from "lucide-react";
import { useAuthStore } from "../store/auth";
import { homePathFor } from "../lib/roles";

export interface SiteNavItem {
  label: string;
  /** In-page anchor (landing) ... */
  href?: string;
  /** ... or a router path. */
  to?: string;
}

interface SoundControls {
  enabled: boolean;
  setEnabled: (v: boolean | ((prev: boolean) => boolean)) => void;
  play: (frequency?: number) => void;
}

/** The WCC Launchpad floating top bar, shared by the landing page and every
 *  public page (gallery, results, voting, verification). Signed-in visitors
 *  get a link to their console instead of log in / join. */
export function SiteTopbar({ items, sound }: { items: SiteNavItem[]; sound?: SoundControls }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const play = (f: number) => sound?.play(f);

  return (
    <header className="top-wrap">
      <nav className="topbar" aria-label="Main navigation">
        <Link to="/" className="brand" onClick={() => play(680)} aria-label="WCC Launchpad home">
          <span className="brand-mark">
            <span>W</span>
          </span>
          <span>
            WCC <small>LAUNCHPAD 30</small>
          </span>
        </Link>

        <div className={`nav-links ${menuOpen ? "nav-links--open" : ""}`}>
          {items.map((item) =>
            item.to ? (
              <Link
                key={item.label}
                to={item.to}
                onClick={() => {
                  play(560);
                  setMenuOpen(false);
                }}
              >
                {item.label}
              </Link>
            ) : (
              <a
                key={item.label}
                href={item.href}
                onClick={() => {
                  play(560);
                  setMenuOpen(false);
                }}
              >
                {item.label}
              </a>
            )
          )}
        </div>

        <div className="nav-actions">
          {sound ? (
            <button
              className="icon-button sound-button"
              type="button"
              aria-label={sound.enabled ? "Turn sound off" : "Turn sound on"}
              onClick={() => sound.setEnabled((v) => !v)}
            >
              {sound.enabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
            </button>
          ) : null}

          {isAuthenticated && user ? (
            <Link className="nav-play" to={homePathFor(user.role)} onClick={() => play(720)}>
              <Gamepad2 size={17} /> MY CONSOLE
            </Link>
          ) : (
            <>
              <Link className="nav-login" to="/login">
                LOG IN
              </Link>
              <Link className="nav-play" to="/register" onClick={() => play(720)}>
                <Rocket size={17} /> JOIN THE BUILD
              </Link>
            </>
          )}

          <button
            className="icon-button menu-button"
            type="button"
            aria-label="Toggle menu"
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? <X /> : <Menu />}
          </button>
        </div>
      </nav>
    </header>
  );
}
