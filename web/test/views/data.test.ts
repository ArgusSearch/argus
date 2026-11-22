// Reads of routes owned by other lanes: a route the API's table marks as a stub is not requested, so the page
// falls back without a failed request in the browser console.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isStub, type RouteInfo } from "../../src/views/data";

const STUB: RouteInfo = { method: "GET", path: "/bench/results", status: "stub" };
const BUILT: RouteInfo = { method: "GET", path: "/bench/results", status: "implemented" };

describe("isStub", () => {
  it("reads the status of exactly that method and path", () => {
    expect(isStub([STUB], "GET", "/bench/results")).toBe(true);
    expect(isStub([BUILT], "GET", "/bench/results")).toBe(false);
    expect(isStub([STUB], "POST", "/bench/results")).toBe(false);
    expect(isStub([STUB], "GET", "/bench")).toBe(false);
  });

  it("marks nothing when the table could not be read", () => {
    expect(isStub(null, "GET", "/bench/results")).toBe(false);
    expect(isStub([], "GET", "/bench/results")).toBe(false);
  });
});

describe("views.benchResults", () => {
  const requested: string[] = [];

  function serve(routes: unknown, scorecard: unknown = { seeds: [] }) {
    vi.stubGlobal("fetch", async (path: string) => {
      requested.push(path);
      if (path === "/routes") return Response.json(routes);
      if (path === "/bench/results") return Response.json(scorecard);
      return new Response("not found", { status: 404 });
    });
  }

  beforeEach(() => {
    requested.length = 0;
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not request a stubbed route", async () => {
    serve([STUB]);
    const { views } = await import("../../src/views/data");
    // a fresh module graph per test, so the error class is the one that module instance sees
    const { ApiError } = await import("../../src/lib/api");
    await expect(views.benchResults()).rejects.toSatisfy((e) => e instanceof ApiError && e.status === 501);
    await expect(views.benchResults()).rejects.toBeInstanceOf(ApiError);
    expect(requested).toEqual(["/routes"]);
  });

  it("reads the route once it is built", async () => {
    serve([BUILT], { seeds: [1, 2, 3] });
    const { views } = await import("../../src/views/data");
    await expect(views.benchResults()).resolves.toEqual({ seeds: [1, 2, 3] });
    expect(requested).toEqual(["/routes", "/bench/results"]);
  });

  it("still tries the route when the table is unreadable", async () => {
    serve("not a table");
    const { views } = await import("../../src/views/data");
    await expect(views.benchResults()).resolves.toEqual({ seeds: [] });
    expect(requested).toEqual(["/routes", "/bench/results"]);
  });
});
