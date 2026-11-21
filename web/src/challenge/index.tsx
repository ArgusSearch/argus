// The blind challenge, mounted around Mission Control: <ChallengeGate><App /></ChallengeGate>.
// Without ?challenge in the URL it renders its children untouched; the screens load lazily.

import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Loading } from "../ui";
import { parseRoute, type Route } from "./route";

const Screens = lazy(() => import("./screens"));

function useRoute(): Route | null {
  const [route, setRoute] = useState(() => parseRoute(window.location.search));
  useEffect(() => {
    const sync = () => setRoute(parseRoute(window.location.search));
    window.addEventListener("popstate", sync);
    window.addEventListener("argus:challenge", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("argus:challenge", sync);
    };
  }, []);
  return route;
}

export function ChallengeGate({ children }: { children: ReactNode }) {
  const route = useRoute();
  if (!route) return <>{children}</>;
  return (
    <>
      {route.screen === "run" && children}
      <Suspense
        fallback={
          route.screen === "run" ? null : (
            <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
              <Loading label="Loading the challenge" />
            </div>
          )
        }
      >
        <Screens route={route} />
      </Suspense>
    </>
  );
}
