import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import BrowserBoot from "./browser/BrowserBoot.jsx";
import { IN_BROWSER } from "./browser/engine.js";
import "./styles/fonts.css";
import "./styles/switch.css";
import { applyTheme, storedMode } from "./theme.js";

// The chosen look's stylesheet goes on before the first render, so a reload
// never flashes the other one.
applyTheme(storedMode());

// In the site's build the engine has to start in the browser first.
const root = IN_BROWSER
  ? <BrowserBoot>{(pending) => <App initialFile={pending} />}</BrowserBoot>
  : <App />;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {root}
  </React.StrictMode>
);
