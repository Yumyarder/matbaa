import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./styles/fonts.css";
import "./styles/switch.css";
import { applyTheme, storedMode } from "./theme.js";

// The chosen look's stylesheet goes on before the first render, so a reload
// never flashes the other one.
applyTheme(storedMode());

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
