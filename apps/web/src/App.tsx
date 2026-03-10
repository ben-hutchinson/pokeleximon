import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Daily from "./pages/Daily";
import Cryptic from "./pages/Cryptic";
import Connections from "./pages/Connections";
import Archive from "./pages/Archive";
import Admin from "./pages/Admin";
import Stats from "./pages/Stats";
import TextOnly from "./pages/TextOnly";
import Leaderboard from "./pages/Leaderboard";
import Challenge from "./pages/Challenge";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/daily" element={<Daily />} />
        <Route path="/cryptic" element={<Cryptic />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/archive" element={<Archive />} />
        <Route path="/stats" element={<Stats />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/challenge/:challengeCode" element={<Challenge />} />
        <Route path="/text-only" element={<TextOnly />} />
        <Route path="/admin" element={<Admin />} />
      </Routes>
    </BrowserRouter>
  );
}
