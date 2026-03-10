import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
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
import Account from "./pages/Account";
import PlayerProfile from "./pages/PlayerProfile";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/daily" element={<Daily />} />
          <Route path="/cryptic" element={<Cryptic />} />
          <Route path="/connections" element={<Connections />} />
          <Route path="/archive" element={<Archive />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/account" element={<Account />} />
          <Route path="/players/:publicSlug" element={<PlayerProfile />} />
          <Route path="/challenge/:challengeCode" element={<Challenge />} />
          <Route path="/text-only" element={<TextOnly />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
