import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./test-utils/server";

// Node v26 defines `localStorage` as `undefined` in the global scope (it requires
// --localstorage-file). Vitest's populateGlobal skips bridging jsdom's localStorage
// when the key already exists on global. Provide a simple in-memory shim so test
// files can use bare `localStorage` without any Node flags.
if (typeof localStorage === "undefined") {
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, String(v)); },
      removeItem: (k: string) => { store.delete(k); },
      clear: () => { store.clear(); },
      get length() { return store.size; },
      key: (i: number) => [...store.keys()][i] ?? null,
    },
    configurable: true,
    writable: true,
  });
}

// jsdom doesn't implement the Pointer Capture APIs that Radix Toast's swipe
// handler calls; stub them so toast interaction tests don't throw uncaught.
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => {};
Element.prototype.releasePointerCapture = () => {};

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
