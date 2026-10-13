import { useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Logo } from "./components/ui";
import Home from "./pages/Home";
import Stories from "./pages/Stories";
import StoryPage from "./pages/StoryPage";
import Methodology from "./pages/Methodology";
import About from "./pages/About";

const REPO = "https://github.com/ananyap-20/underdog-sports-bot-v2";

export default function App() {
  const [open, setOpen] = useState(false);
  useLocation();
  const cls = ({ isActive }: { isActive: boolean }) => `link${isActive ? " active" : ""}`;
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <nav className="wrap nav" aria-label="Main">
          <Link to="/" className="brand" onClick={() => setOpen(false)}><Logo /> Underdog Sports Bot</Link>
          <button className="btn small menu-btn" aria-expanded={open} aria-controls="menu" onClick={() => setOpen(!open)}>Menu</button>
          <ul id="menu" className={open ? "open" : ""} onClick={() => setOpen(false)}>
            <li><NavLink to="/" end className={cls}>Home</NavLink></li>
            <li><NavLink to="/stories" className={cls}>Stories</NavLink></li>
            <li><NavLink to="/methodology" className={cls}>How it works</NavLink></li>
            <li><NavLink to="/about" className={cls}>About</NavLink></li>
          </ul>
        </nav>
      </header>
      <main id="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/stories" element={<Stories />} />
          <Route path="/stories/:id" element={<StoryPage />} />
          <Route path="/methodology" element={<Methodology />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<div className="wrap section"><h2>Page not found</h2><p><Link to="/">Back to home</Link></p></div>} />
        </Routes>
      </main>
      <footer>
        <div className="wrap">
          <p>Underdog Sports Bot is an evidence-assisted discovery tool. It does not decide who deserves recognition, and automated screening can be wrong.</p>
          <p className="small">Found a factual error or a broken link? <a href={`${REPO}/issues`} target="_blank" rel="noopener noreferrer">Open an issue on GitHub</a>.</p>
        </div>
      </footer>
    </>
  );
}
