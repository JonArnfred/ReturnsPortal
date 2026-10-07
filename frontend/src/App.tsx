import { useRoutes } from "react-router-dom";
import { PrivacyProvider } from "./app/privacy";
import { createAppRoutes } from "./app/routes";
import type { InitialData } from "./initialData";
import NotFoundPage from "./pages/NotFoundPage";

export default function App({ initialData }: { initialData?: InitialData }) {
  const routes = useRoutes([...createAppRoutes(), { path: "*", element: <NotFoundPage /> }]);
  return <PrivacyProvider initialHidden={initialData?.hideAmounts ?? false}>{routes}</PrivacyProvider>;
}
