// The clock a live shop shows: the real current time in Berlin, the same zone and format as the sign-in's last
// check. A recorded example history keeps its own simulated time, because that is the time its numbers belong to.

import { useEffect, useState } from "react";
import { useAppState } from "./AppState";

const BERLIN = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});

/** "15:41 CET": the real time in Berlin. */
export function berlinTime(now: Date): string {
  return BERLIN.format(now);
}

/** The current time, repainted at each minute boundary. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const at = new Date();
      setNow(at);
      timer = setTimeout(tick, 60_000 - (at.getTime() % 60_000) + 50);
    };
    timer = setTimeout(tick, 60_000 - (Date.now() % 60_000) + 50);
    return () => clearTimeout(timer);
  }, []);
  return now;
}

/** The workspace clock: the real Berlin time for a live shop, the simulated shop time for a recorded history. */
export function useShopClock(): { label: string | null; title: string } {
  const { monitor, health } = useAppState();
  const now = useNow();
  if (health?.mode === "live") return { label: berlinTime(now), title: "Current time in Berlin" };
  return { label: monitor.timeLabel, title: "Shop time in UTC" };
}
