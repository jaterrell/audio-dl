import { describe, it, expect, beforeEach } from "vitest";
import { toast, getToasts, resetToastStore, setMaxToasts } from "./toast-store";

beforeEach(() => resetToastStore());

describe("toast store", () => {
  it("adds a toast and returns its id", () => {
    const id = toast.success("Saved");
    expect(typeof id).toBe("string");
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "success", title: "Saved" });
  });

  it("dismisses a toast by id", () => {
    const id = toast.info("Hi");
    toast.dismiss(id);
    expect(getToasts()).toHaveLength(0);
  });

  it("dismiss() with no id clears all toasts", () => {
    toast.info("a");
    toast.error("b");
    toast.dismiss();
    expect(getToasts()).toHaveLength(0);
  });

  it("caps at max, evicting the oldest (newest first)", () => {
    setMaxToasts(2);
    toast.info("1");
    toast.info("2");
    toast.info("3");
    expect(getToasts().map((t) => t.title)).toEqual(["3", "2"]);
  });

  it("updates in place when an explicit id is reused", () => {
    toast.loading("Working", { id: "x" });
    toast.success("Done", { id: "x" });
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ id: "x", variant: "success", title: "Done" });
  });

  it("applies per-variant default durations (error sticky, success 4s)", () => {
    const e = toast.error("boom");
    const s = toast.success("ok");
    const byId = (id: string) => getToasts().find((t) => t.id === id)!;
    expect(byId(e).duration).toBe(Number.POSITIVE_INFINITY);
    expect(byId(s).duration).toBe(4000);
  });

  it("honours an explicit duration override", () => {
    const id = toast.error("boom", { duration: 9000 });
    expect(getToasts().find((t) => t.id === id)!.duration).toBe(9000);
  });
});

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("toast.promise", () => {
  it("starts as loading", () => {
    toast.promise(new Promise(() => {}), { loading: "Loading", success: "OK", error: "Err" });
    expect(getToasts()[0]).toMatchObject({ variant: "loading", title: "Loading" });
  });

  it("morphs the same toast loading -> success", async () => {
    toast.promise(Promise.resolve("v"), {
      loading: "Loading",
      success: (v) => `Got ${v}`,
      error: "Err",
    });
    await flush();
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "success", title: "Got v" });
  });

  it("morphs the same toast loading -> error on reject", async () => {
    toast.promise(Promise.reject(new Error("nope")), {
      loading: "L",
      success: "S",
      error: (e) => (e as Error).message,
    });
    await flush();
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({ variant: "error", title: "nope" });
  });
});
