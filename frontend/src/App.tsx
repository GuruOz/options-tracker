import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AccountProvider } from "./hooks/useAccount";
import { DisplayCurrencyProvider } from "./hooks/useDisplayCurrency";
import { ScopeProvider } from "./hooks/useScope";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { LoginPage } from "./components/LoginPage";
import { AppLayout } from "./layout/AppLayout";
import { HomePage } from "./pages/HomePage";
import { OptionsPage } from "./pages/OptionsPage";
import { UploadsPage } from "./pages/UploadsPage";
import { NetWorthPage } from "./pages/NetWorthPage";
import { PlanPage } from "./pages/PlanPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}

function Gate() {
  const { status } = useAuth();

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
        <p className="text-sm text-slate-400 dark:text-slate-500">Loading…</p>
      </div>
    );
  }
  if (status === "anon") {
    return <LoginPage />;
  }
  return (
    <AccountProvider>
      <ScopeProvider>
        <DisplayCurrencyProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<HomePage />} />
                <Route path="networth" element={<NetWorthPage />} />
                <Route path="options" element={<OptionsPage />} />
                <Route path="plan" element={<PlanPage />} />
                <Route path="uploads" element={<UploadsPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </DisplayCurrencyProvider>
      </ScopeProvider>
    </AccountProvider>
  );
}
