// Browser storage that never throws. Inside some embedded previews and private
// browsing modes, touching localStorage raises a security error; the app then keeps
// working with an in-memory copy (the session simply does not survive a reload).

const memory = new Map<string, string>();

function store(): Storage | null {
  try {
    const candidate = window.localStorage;
    candidate.getItem("tatmaq:probe");
    return candidate;
  } catch {
    return null;
  }
}

export const safeStorage = {
  get(key: string): string | null {
    if (typeof window === "undefined") return null;
    try {
      return store()?.getItem(key) ?? memory.get(key) ?? null;
    } catch {
      return memory.get(key) ?? null;
    }
  },
  set(key: string, value: string): void {
    memory.set(key, value);
    try {
      store()?.setItem(key, value);
    } catch {
      /* memory copy is enough */
    }
  },
  remove(key: string): void {
    memory.delete(key);
    try {
      store()?.removeItem(key);
    } catch {
      /* nothing to remove */
    }
  },
};
