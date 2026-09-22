import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import { createWriteStream, mkdirSync } from "node:fs";
import path from "node:path";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { PROTOCOL_VERSION, type ControllerEvent } from "./shared.js";

interface PendingRequest {
  resolve(value: Record<string, unknown>): void;
  reject(error: Error): void;
  timer: NodeJS.Timeout;
}

interface ResponseMessage {
  v: number;
  kind: "response";
  id: string;
  ok: boolean;
  result?: Record<string, unknown>;
  error?: { code?: string; message?: string };
}

export class DesktopControllerClient extends EventEmitter {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly pending = new Map<string, PendingRequest>();
  private buffer = "";
  private readyResolve!: () => void;
  private readyReject!: (error: Error) => void;
  private readonly readyPromise: Promise<void>;
  private closed = false;

  constructor(executable: string, args: string[], logFile: string, environment: NodeJS.ProcessEnv = process.env) {
    super();
    mkdirSync(path.dirname(logFile), { recursive: true, mode: 0o700 });
    const log = createWriteStream(logFile, { flags: "a", mode: 0o600 });
    this.child = spawn(executable, args, {
      env: environment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child.stderr.pipe(log, { end: false });
    this.readyPromise = new Promise<void>((resolve, reject) => {
      this.readyResolve = resolve;
      this.readyReject = reject;
    });
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk: string) => this.accept(chunk));
    this.child.once("error", (error) => this.fail(error));
    this.child.once("exit", (code, signal) => {
      log.end();
      const error = new Error(`desktop_controller_exit:${code ?? "signal"}:${signal ?? "none"}`);
      this.fail(error);
      this.emit("exit", { code, signal });
    });
  }

  private accept(chunk: string): void {
    this.buffer += chunk;
    if (this.buffer.length > 2 * 1024 * 1024) {
      this.fail(new Error("desktop_controller_output_too_large"));
      this.child.kill();
      return;
    }
    for (;;) {
      const newline = this.buffer.indexOf("\n");
      if (newline < 0) break;
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (!line) continue;
      let value: ControllerEvent | ResponseMessage;
      try {
        value = JSON.parse(line) as ControllerEvent | ResponseMessage;
      } catch {
        this.fail(new Error("desktop_controller_invalid_json"));
        this.child.kill();
        return;
      }
      if (value.v !== PROTOCOL_VERSION) {
        this.fail(new Error("desktop_controller_protocol_mismatch"));
        this.child.kill();
        return;
      }
      if (value.kind === "event") {
        if (value.event === "control_ready") this.readyResolve();
        this.emit("event", value);
        continue;
      }
      if (value.kind === "response" && typeof value.id === "string") {
        const request = this.pending.get(value.id);
        if (!request) continue;
        clearTimeout(request.timer);
        this.pending.delete(value.id);
        if (value.ok) request.resolve(value.result ?? {});
        else request.reject(new Error(`${value.error?.code ?? "controller_error"}:${value.error?.message ?? ""}`));
      }
    }
  }

  private fail(error: Error): void {
    if (this.closed) return;
    this.closed = true;
    this.readyReject(error);
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }

  async ready(timeoutMs = 20_000): Promise<void> {
    let timer: NodeJS.Timeout | undefined;
    try {
      await Promise.race([
        this.readyPromise,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("desktop_controller_start_timeout")), timeoutMs);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async request(command: string, payload: Record<string, unknown> = {}, timeoutMs = 300_000):
    Promise<Record<string, unknown>> {
    await this.ready();
    if (this.closed || !this.child.stdin.writable) throw new Error("desktop_controller_unavailable");
    const id = randomUUID();
    const result = new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`desktop_controller_timeout:${command}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
    });
    this.child.stdin.write(`${JSON.stringify({ v: PROTOCOL_VERSION, id, command, payload })}\n`);
    return result;
  }

  onEvent(listener: (event: ControllerEvent) => void): () => void {
    this.on("event", listener);
    return () => this.off("event", listener);
  }

  async close(): Promise<void> {
    if (this.child.exitCode !== null || this.child.killed) return;
    try {
      await this.request("shutdown", {}, 5_000);
    } catch {
      // EOF and process termination are the final cleanup guarantee.
    }
    this.child.stdin.end();
    await new Promise<void>((resolve) => {
      if (this.child.exitCode !== null) return resolve();
      const timer = setTimeout(() => {
        this.child.kill("SIGTERM");
        resolve();
      }, 5_000);
      this.child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
}
