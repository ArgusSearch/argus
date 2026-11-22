// The reads the settings pages make on their own: GET /autonomy (what each agent may do alone) and GET /health
// (the watcher's lines and the run's source). Read once per stream; a failed read shows as an error state, never as
// a made-up value.

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Health } from "../lib/types";
import type { Autonomy } from "./model";

interface Loaded<T> {
  data: T | null;
  error: string | null;
}

const LOADING = { data: null, error: null };

function useRead<T>(read: () => Promise<T>, stream: string | null): Loaded<T> {
  const [result, setResult] = useState<(Loaded<T> & { stream: string | null }) | null>(null);
  useEffect(() => {
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
  return result?.stream === stream ? result : LOADING;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} answered ${res.status}`);
  return (await res.json()) as T;
}

const readAutonomy = () => getJson<Autonomy>("/autonomy");
const readHealth = () => api.health();

export function useAutonomy(stream: string | null): Loaded<Autonomy> {
  return useRead(readAutonomy, stream);
}

export function useHealth(stream: string | null): Loaded<Health> {
  return useRead(readHealth, stream);
}
