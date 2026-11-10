import { callable } from "@decky/api";
import type { DiagnosticSnapshot, Envelope } from "./types";

export const getSnapshot = callable<[], Envelope<DiagnosticSnapshot>>("get_snapshot");
export const getDiagnostics = callable<[moduleId?: string], Envelope<DiagnosticSnapshot>>("get_diagnostics");
export const probeModule = callable<[moduleId: string], Envelope<{ module: DiagnosticSnapshot["modules"][number] }>>("probe_module");
export const ping = callable<[], Envelope<{ pong: boolean; phase: string; hardware_validated: boolean }>>("ping");
export const emitProbeEvent = callable<[], Envelope<{ epoch: string; revision: number; domain: string }>>("emit_probe_event");
export const readRedumperVersion = callable<[allowUntestedWrapper?: boolean], Envelope<Record<string, unknown>>>("read_redumper_version");

export const PHASE0_PUBLIC_HELPERS = [
  "callable",
  "addEventListener",
  "removeEventListener",
  "definePlugin",
  "toaster",
  "useQuickAccessVisible",
] as const;
