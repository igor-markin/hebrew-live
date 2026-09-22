export interface BackendState {
  running?: boolean;
  ready?: boolean;
  paused?: boolean;
  finished?: boolean;
  stopping?: boolean;
  phase?: string;
  recording_started?: boolean;
  capture_active?: boolean;
}

export type QuitSituation = "idle" | "preparing" | "recording";

export function quitSituation(preparing: boolean, state: BackendState | null): QuitSituation {
  if (preparing) return "preparing";
  if (!state?.running || state.finished) return "idle";
  if (state.recording_started === true) return "recording";
  if (state.recording_started === false || state.ready === false || state.phase === "loading" || state.phase === "opening") return "idle";
  if (state.paused && !state.stopping) return "idle";
  return "recording";
}
