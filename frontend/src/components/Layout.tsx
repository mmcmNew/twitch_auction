import { Link, NavLink, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <div className="app-shell">
      <header>
        <Link to="/" className="brand">Twitch Auction</Link>
        <nav>
          <NavLink to="/viewer">Viewer</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/overlay">Overlay</NavLink>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
