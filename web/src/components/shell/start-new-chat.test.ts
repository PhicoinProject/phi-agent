import { beforeEach, describe, expect, it, vi } from "vitest";

import { startNewChat, takeOpenSeed } from "./start-new-chat";

const api = vi.hoisted(() => ({ newChat: vi.fn() }));
vi.mock("@/lib/api-workspace", () => ({ workspaceApi: api }));

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (e: Error) => void = () => {};
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("startNewChat", () => {
  beforeEach(() => {
    api.newChat.mockReset();
  });

  it("asks for the space's New chat room once, then opens it", async () => {
    const created = deferred<{ room_id: string }>();
    api.newChat.mockReturnValue(created.promise);
    const openRoom = vi.fn();

    const started = startNewChat("!space-a", openRoom);
    await Promise.resolve();
    expect(api.newChat).toHaveBeenCalledTimes(1);
    expect(api.newChat).toHaveBeenCalledWith("!space-a");
    expect(openRoom).not.toHaveBeenCalled();

    created.resolve({ room_id: "0123456789abcdef" });
    await expect(started).resolves.toBe("0123456789abcdef");
    expect(openRoom).toHaveBeenCalledTimes(1);
    expect(openRoom).toHaveBeenCalledWith("0123456789abcdef");
  });

  it("uses the given create call (the shell's, which also refreshes the list) instead of the bare API", async () => {
    const create = vi.fn().mockResolvedValue({ room_id: "fedcba9876543210" });
    const openRoom = vi.fn();
    await startNewChat(null, openRoom, create);
    expect(create).toHaveBeenCalledWith(null);
    expect(api.newChat).not.toHaveBeenCalled();
    expect(openRoom).toHaveBeenCalledWith("fedcba9876543210");
  });

  it("opens nothing when the room cannot be made", async () => {
    api.newChat.mockRejectedValue(new Error("unknown space"));
    const openRoom = vi.fn();
    await expect(startNewChat(null, openRoom)).rejects.toThrow("unknown space");
    expect(openRoom).not.toHaveBeenCalled();
  });
});

describe("takeOpenSeed", () => {
  it("types a ?learn= seed once and drops it from the URL", () => {
    const setParams = vi.fn();
    const seed = takeOpenSeed(new URLSearchParams("room=0123456789abcdef&learn=topic"), setParams);
    expect(seed).toBe("/learn topic");
    const [next, opts] = setParams.mock.calls[0];
    expect((next as URLSearchParams).get("learn")).toBeNull();
    expect((next as URLSearchParams).get("room")).toBe("0123456789abcdef");
    expect(opts).toEqual({ replace: true });
  });

  it("is nothing without a seed", () => {
    const setParams = vi.fn();
    expect(takeOpenSeed(new URLSearchParams("room=0123456789abcdef"), setParams)).toBeNull();
    expect(setParams).not.toHaveBeenCalled();
  });
});
