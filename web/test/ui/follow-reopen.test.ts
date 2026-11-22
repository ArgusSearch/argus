// follow() reopens a stream the browser closed for good (a non-200 answer, e.g. the dev proxy's 502 while
// the API is down): the page recovers when the API is back instead of staying offline until a reload.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { follow, RETRY_CLOSED_MS, type ConnectionState } from "../../src/lib/api";

class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static created: FakeEventSource[] = [];
  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.created.push(this);
  }
  addEventListener(): void {}
  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }
  /** A non-200 answer: the browser closes the stream and does not retry. */
  refuse(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.();
  }
}

describe("follow: a stream closed for good is reopened", () => {
  let states: ConnectionState[];
  let stop: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    FakeEventSource.created = [];
    states = [];
    stop = follow({ onReset: () => undefined, onEvents: () => undefined, onState: (s) => states.push(s) });
  });

  afterEach(() => {
    stop();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("stays offline without flicker while refused, and opens when the API is back", () => {
    FakeEventSource.created[0].refuse();
    expect(states.at(-1)).toBe("offline");
    vi.advanceTimersByTime(RETRY_CLOSED_MS);
    expect(FakeEventSource.created).toHaveLength(2);
    expect(states.at(-1)).toBe("offline"); // no flicker back to "connecting" while it is still down
    FakeEventSource.created[1].refuse();
    vi.advanceTimersByTime(RETRY_CLOSED_MS);
    FakeEventSource.created[2].open();
    expect(states.at(-1)).toBe("open");
    expect(states.filter((s) => s === "connecting")).toHaveLength(1); // only the first connect
  });

  it("stops reopening once the page unsubscribes", () => {
    FakeEventSource.created[0].refuse();
    stop();
    vi.advanceTimersByTime(RETRY_CLOSED_MS * 3);
    expect(FakeEventSource.created).toHaveLength(1);
    stop = () => undefined;
  });
});
