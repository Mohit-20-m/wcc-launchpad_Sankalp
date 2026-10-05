import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/auth";

export function useSignOut(): () => void {
  const navigate = useNavigate();
  const clearSession = useAuthStore((s) => s.clearSession);
  return () => {
    clearSession();
    navigate("/login", { replace: true });
  };
}
