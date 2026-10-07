/// <reference types="vite/client" />

import type { InitialData } from "./initialData";

declare global {
  interface Window {
    __RETURNS_PORTAL_INITIAL_DATA__?: InitialData;
  }
}
