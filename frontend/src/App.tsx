import { Route, Routes } from "react-router-dom";

import { AuthGate } from "./components/AuthGate";
import { QuickLogProvider } from "./components/QuickLog";
import Shell from "./layout/Shell";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Tires from "./pages/Tires";
import VehiclePage from "./pages/VehiclePage";
import Vehicles from "./pages/Vehicles";

export default function App() {
  return (
    <AuthGate>
    <QuickLogProvider>
      <Routes>
        <Route path="/vehicles/:id/history" element={<History />} />
        <Route element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="/vehicles" element={<Vehicles />} />
          <Route path="/vehicles/:id" element={<VehiclePage />} />
          <Route path="/tires" element={<Tires />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </QuickLogProvider>
    </AuthGate>
  );
}
