/**
 * Runs `work` and reports when it is taking a long time.
 *
 * A free hosting plan puts the server to sleep when nobody is using it, and the first
 * request afterwards waits a minute or two while it starts. Saying so is the difference
 * between "it is starting" and "it is broken". `onSlow(true)` fires if the work is still
 * going after `afterMs`; `onSlow(false)` fires when it ends, either way.
 */
export async function noticeIfSlow<T>(onSlow: (slow: boolean) => void, work: () => Promise<T>, afterMs = 4000): Promise<T> {
  const timer = window.setTimeout(() => onSlow(true), afterMs);
  try {
    return await work();
  } finally {
    window.clearTimeout(timer);
    onSlow(false);
  }
}

export const SERVER_STARTING = "The server is starting up. This can take a minute or two; please wait.";
