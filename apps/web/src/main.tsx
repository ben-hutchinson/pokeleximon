import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initSentry } from "./observability/sentry";
import "./styles.css";

initSentry();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
