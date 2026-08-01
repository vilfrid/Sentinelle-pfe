import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ProtectedRoute from "./components/ProtectedRoute";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Campaigns from "./pages/Campaigns";
import Creators from "./pages/Creators";
import CreatorProfile from "./pages/CreatorProfile";
import Comments from "./pages/Comments";
import Analytics from "./pages/Analytics";
import Reports from "./pages/Reports";
import Matching from "./pages/Matching";
import Pipeline from "./pages/Pipeline";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      {/* Everything below requires a valid JWT session */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard"        element={<Dashboard />} />
          <Route path="/campaigns"        element={<Campaigns />} />
          <Route path="/creators"         element={<Creators />} />
          <Route path="/creators/:id"     element={<CreatorProfile />} />
          <Route path="/comments"         element={<Comments />} />
          <Route path="/analytics"        element={<Analytics />} />
          <Route path="/reports"          element={<Reports />} />
          <Route path="/matching"          element={<Matching />} />
          <Route path="/pipeline"          element={<Pipeline />} />
        </Route>
      </Route>
    </Routes>
  );
}
