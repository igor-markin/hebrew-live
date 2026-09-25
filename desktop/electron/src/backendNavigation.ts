/** Retry the local backend page briefly, then let the caller show recovery UI. */
export interface BackendPageTarget {
  loadURL(url: string): Promise<void>;
  isDestroyed(): boolean;
  webContents: { stop(): void };
}

export async function navigateBackend(
  target: BackendPageTarget,
  url: string,
  current: () => boolean,
  options: {
    attempts?: number;
    timeoutMs?: number;
    wait?: (ms: number) => Promise<void>;
  } = {},
): Promise<boolean> {
  const attempts = options.attempts ?? 3;
  const timeoutMs = options.timeoutMs ?? 5_000;
  const wait = options.wait ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (!current() || target.isDestroyed()) return false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let timedOut = false;
    try {
      await Promise.race([
        target.loadURL(url),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(() => {
            timedOut = true;
            reject(new Error("backend_navigation_timeout"));
          }, timeoutMs);
        }),
      ]);
      return current() && !target.isDestroyed();
    } catch {
      if (timedOut && !target.isDestroyed()) target.webContents.stop();
    } finally {
      if (timer) clearTimeout(timer);
    }
    if (attempt + 1 < attempts) await wait(250 * (attempt + 1));
  }
  return false;
}
