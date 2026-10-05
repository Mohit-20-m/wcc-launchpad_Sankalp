import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <main className="auth-page">
      <div className="pixel-grid" aria-hidden="true" />
      <div className="auth-inner">
        <div className="auth-head">
          <span className="chip chip--coral">ERROR 404</span>
          <h1>
            LEVEL <em>NOT FOUND.</em>
          </h1>
          <p>That page doesn't exist, or it moved. Head back to the arena.</p>
        </div>
        <Link to="/" className="auth-back">
          <ArrowLeft size={14} /> BACK TO HOME
        </Link>
      </div>
    </main>
  );
}
