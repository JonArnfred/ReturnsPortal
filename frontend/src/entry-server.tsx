import createEmotionServer from "@emotion/server/create-instance";
import React from "react";
import { renderToString } from "react-dom/server";
import { matchRoutes, StaticRouter } from "react-router-dom";
import App from "./App";
import { createAppRoutes } from "./app/routes";
import type { InitialData } from "./initialData";
import { createEmotionCache } from "./theme/emotionCache";
import Providers from "./theme/Providers";

export function render(url: string, initialData: InitialData = {}) {
  const pathname = new URL(url, "http://localhost").pathname;
  const cache = createEmotionCache();
  const { extractCriticalToChunks, constructStyleTagsFromChunks } = createEmotionServer(cache);
  const html = renderToString(
    <React.StrictMode>
      <Providers cache={cache}>
        <StaticRouter location={url}>
          <App initialData={initialData} />
        </StaticRouter>
      </Providers>
    </React.StrictMode>,
  );
  const css = constructStyleTagsFromChunks(extractCriticalToChunks(html));
  return {
    html,
    css,
    statusCode: matchRoutes(createAppRoutes(), pathname) ? 200 : 404,
  };
}
