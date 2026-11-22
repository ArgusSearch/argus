// The run's autonomy rule catalog, playbooks, and source health. Read these once per stream.

import { useEffect, useState } from "react";
import { api, json } from "../lib/api";
import { staticReplay } from "../lib/deployment";
import type { Health } from "../lib/types";
import type { Autonomy } from "./model";

interface Loaded<T> {
  data: T | null;
  error: string | null;
}

const LOADING = { data: null, error: null };
const RECORDED = { data: null, error: "The live API is unavailable." };

function useRead<T>(read: () => Promise<T>, stream: string | null): Loaded<T> {
  const [result, setResult] = useState<(Loaded<T> & { stream: string | null }) | null>(null);
  useEffect(() => {
    if (staticReplay) return;
    let current = true;
    void read().then(
      (data) => {
        if (current) setResult({ stream, data, error: null });
      },
      (error: unknown) => {
        if (current) setResult({ stream, data: null, error: error instanceof Error ? error.message : String(error) });
      },
    );
    return () => {
      current = false;
    };
  }, [read, stream]);
  if (staticReplay) return RECORDED;
  return result?.stream === stream ? result : LOADING;
}

const readAutonomy = () => json<Autonomy>("/autonomy");
const readHealth = () => api.health();

export function useAutonomy(stream: string | null): Loaded<Autonomy> {
  return useRead(readAutonomy, stream);
}

export function useHealth(stream: string | null): Loaded<Health> {
  return useRead(readHealth, stream);
}
