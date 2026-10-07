import React from "react";
import { hydrateRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";
import { createEmotionCache } from "./theme/emotionCache";
import Providers from "./theme/Providers";

const cache = createEmotionCache();

hydrateRoot(
  document.getElementById("root")!,
  <React.StrictMode>
    <Providers cache={cache}>
      <BrowserRouter>
        <App initialData={window.__RETURNS_PORTAL_INITIAL_DATA__} />
      </BrowserRouter>
    </Providers>
  </React.StrictMode>,
  {
    onRecoverableError(error, errorInfo) {
      if (import.meta.env.DEV) {
        console.error("[hydration]", error, errorInfo.componentStack);
      }
    },
  },
);
