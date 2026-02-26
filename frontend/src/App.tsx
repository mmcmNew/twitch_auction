import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { DashboardPage, OverlayPage, ViewerPage } from "./pages";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/viewer" replace />} />
        <Route path="viewer" element={<ViewerPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="overlay" element={<OverlayPage />} />
      </Route>
    </Routes>
  );
}
