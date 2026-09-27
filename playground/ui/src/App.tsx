// App shell: top navigation and hash routes. Demos stay mounted so edits survive tab switches.
import { useEffect, useState } from "react";
import { api, track, type Config } from "./api";
import { ChatDemo } from "./pages/ChatDemo";
import { SessionsDemo } from "./pages/SessionsDemo";
import { Evaluation } from "./pages/Evaluation";
import { Integrate } from "./pages/Integrate";

const ROUTES = [
  ["", "Chat demo"],
  ["sessions", "Coding sessions"],
  ["eval", "Evaluation"],
  ["integrate", "Integrate"],
] as const;
type Route = (typeof ROUTES)[number][0];

const routeFromHash = (): Route => {
  const r = location.hash.replace(/^#\/?/, "");
  return (ROUTES.find(([id]) => id === r)?.[0] ?? "") as Route;
};

function useDark(): boolean {
  const q = window.matchMedia("(prefers-color-scheme: dark)");
  const [dark, setDark] = useState(q.matches);
  useEffect(() => {
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, [q]);
  return dark;
}

export function App() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [seen, setSeen] = useState<Set<Route>>(new Set([routeFromHash()]));
  const dark = useDark();

  useEffect(() => {
    api.config().then(setCfg);
    track("visit");
    const on = () => { const r = routeFromHash(); setRoute(r); setSeen((s) => new Set(s).add(r)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="logo" aria-hidden="true" />Mem<span>worthy</span>
          <span className="tag">playground</span>
        </a>
        <nav aria-label="Pages">
          {ROUTES.map(([id, label]) => (
            <a key={id} href={`#/${id}`} aria-current={route === id ? "page" : undefined}>{label}</a>
          ))}
          <a href="https://github.com/AfnanHussain10/Memworthy" rel="noopener" onClick={() => track("github")}>GitHub ↗</a>
        </nav>
      </header>
      <main id="main">
        {!cfg && <p className="muted pad">Loading…</p>}
        {cfg && (
          <>
            <div hidden={route !== ""}><ChatDemo cfg={cfg} dark={dark} /></div>
            {seen.has("sessions") && <div hidden={route !== "sessions"}><SessionsDemo cfg={cfg} dark={dark} /></div>}
            {route === "eval" && <Evaluation />}
            {route === "integrate" && <Integrate />}
          </>
        )}
      </main>
    </>
  );
}
