import { BrowserRouter, Route, Routes } from "react-router-dom";
import { RequireRole } from "./components/RequireRole";
import Gallery from "./pages/Gallery";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Register from "./pages/Register";
import Results from "./pages/Results";
import Verify from "./pages/Verify";
import Vote from "./pages/Vote";
import JudgeConsole from "./pages/console/JudgeConsole";
import OrganizerConsole from "./pages/console/OrganizerConsole";
import ParticipantConsole from "./pages/console/ParticipantConsole";

/** Route table, separate from the router so tests can mount it in a
 *  MemoryRouter. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/gallery" element={<Gallery />} />
      <Route path="/vote/:eventId" element={<Vote />} />
      <Route path="/results/:eventId" element={<Results />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/verify/:code" element={<Verify />} />

      {/* Each console is guarded by role in the UI; the backend re-checks
          the role on every API call, so this is convenience, not security. */}
      <Route
        path="/participant"
        element={
          <RequireRole role="participant">
            <ParticipantConsole />
          </RequireRole>
        }
      />
      <Route
        path="/judge"
        element={
          <RequireRole role="judge">
            <JudgeConsole />
          </RequireRole>
        }
      />
      <Route
        path="/organizer"
        element={
          <RequireRole role="organizer">
            <OrganizerConsole />
          </RequireRole>
        }
      />

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
