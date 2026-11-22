import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { follow, OFFLINE_AFTER_MS, type ConnectionState } from "../src/lib/api";

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static last: FakeEventSource | null = null;
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(): void {}
  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }
  /** When the server is gone, the browser reports an error and would reconnect on its own. */
  fail(readyState: number = FakeEventSource.CONNECTING): void {
    this.readyState = readyState;
    this.onerror?.();
  }
}

describe("follow: connection state", () => {
  let states: ConnectionState[];
  let stop: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    states = [];
    stop = follow({ onReset: () => undefined, onEvents: () => undefined, onState: (s) => states.push(s) });
  });

  afterEach(() => {
    stop();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("says offline when the stream keeps failing to reconnect (#6)", () => {
    const es = FakeEventSource.last!;
    es.open();
    es.fail();
    expect(states.at(-1)).toBe("connecting");
    vi.advanceTimersByTime(OFFLINE_AFTER_MS - 1);
    const reconnect = FakeEventSource.last!;
    expect(reconnect).not.toBe(es);
    expect(reconnect.url).toBe("/events?include_stream=true");
    reconnect.fail();
    expect(states.at(-1)).toBe("connecting");
    vi.advanceTimersByTime(1);
    expect(states.at(-1)).toBe("offline");
    vi.advanceTimersByTime(OFFLINE_AFTER_MS);
    FakeEventSource.last!.fail(); // further retries keep the banner
    expect(states.at(-1)).toBe("offline");
  });

  it("recovers to open when the API comes back", () => {
    const es = FakeEventSource.last!;
    es.open();
    es.fail();
    expect(es.readyState).toBe(FakeEventSource.CLOSED);
    vi.advanceTimersByTime(OFFLINE_AFTER_MS);
    expect(states.at(-1)).toBe("offline");
    const fresh = FakeEventSource.last!;
    expect(fresh).not.toBe(es);
    expect(fresh.url).toBe("/events?include_stream=true");
    fresh.open();
    expect(states.at(-1)).toBe("open");
  });

  it("shows offline immediately when the browser closes the stream", () => {
    expect(states).toEqual(["connecting"]);
    const es = FakeEventSource.last!;
    es.fail(FakeEventSource.CLOSED);
    expect(states.at(-1)).toBe("offline");
    vi.advanceTimersByTime(OFFLINE_AFTER_MS / 2);
    const fresh = FakeEventSource.last!;
    expect(fresh).not.toBe(es);
    fresh.open();
    expect(states.at(-1)).toBe("open");
  });

  it("a short blip that reconnects in time never shows offline", () => {
    const es = FakeEventSource.last!;
    es.open();
    es.fail();
    vi.advanceTimersByTime(OFFLINE_AFTER_MS / 2);
    FakeEventSource.last!.open();
    vi.advanceTimersByTime(OFFLINE_AFTER_MS * 2);
    expect(states).not.toContain("offline");
    expect(states.at(-1)).toBe("open");
  });
});
