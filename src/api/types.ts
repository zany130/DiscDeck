export type CapabilityState =
  | "ready"
  | "missing"
  | "denied"
  | "unsupported"
  | "untested"
  | "degraded";

export type EffectiveState =
  | "active"
  | "disabled"
  | "unavailable"
  | "busy"
  | "disable_pending";

export interface ModuleStatus {
  id: string;
  enabled: boolean;
  capability: CapabilityState | string;
  effective: EffectiveState | string;
  reason_code?: string | null;
  message?: string;
  checked_at: string;
  hardware_validated?: boolean;
  details?: Record<string, string | number | boolean | null>;
}

export interface DriveObservation {
  drive_id: string;
  block_node: string;
  generic_scsi_node?: string | null;
  vendor?: string;
  model?: string;
  scsi_address?: string | null;
  lun?: number | null;
  usb_id?: string | null;
  usb_port?: string | null;
  shared_bridge?: boolean;
  optical?: boolean;
  media_present?: boolean | "unknown";
  generation?: number;
  media_generation?: number;
  filesystem?: boolean;
  hardware_validated?: boolean;
  operations?: Record<string, string>;
}

export interface DiagnosticSnapshot {
  epoch: string;
  revision: number;
  phase: string;
  hardware_validated: boolean;
  settings_revision: number;
  modules: ModuleStatus[];
  drives: DriveObservation[];
  virtual_slots: unknown[];
  jobs: unknown[];
  identity: {
    effective_user?: string | null;
    effective_uid?: number | null;
    effective_gid?: number | null;
    owner_user?: string | null;
    owner_uid?: number | null;
    root_requested?: boolean;
    loader_version?: string | null;
    plugin_version?: string | null;
    privilege?: { status?: string; dropped?: boolean };
    directories?: Record<string, { path?: string | null; exists?: boolean; writable?: boolean; durability?: string }>;
  };
  probes?: {
    redumper?: {
      path?: string | null;
      status?: string;
      version?: string | null;
      version_status?: string;
      launch_kind?: string;
      executed?: boolean;
      message?: string;
      reason_code?: string;
    };
    cdemu?: {
      status?: string;
      reason_code?: string;
      message?: string;
      active?: boolean;
      vhba_loaded?: boolean;
      vhba_ctl_present?: boolean;
    };
    steam?: {
      status?: string;
      steam_binary?: string | null;
      library_paths?: string[];
      compatibility_tools?: { name: string }[];
      shortcuts_read?: boolean;
      launched?: boolean;
      message?: string;
    };
    udisks2?: { status?: string; reason_code?: string | null; message?: string };
  };
  limitations?: string[];
  build?: { commit?: string | null; channel?: string; hardware_validated?: boolean };
}

export interface SuccessEnvelope<T> {
  ok: true;
  result: T;
  revision: number;
  epoch?: string;
}

export interface ErrorEnvelope {
  ok: false;
  code: string;
  message: string;
  retryable: boolean;
  revision?: number;
  epoch?: string;
}

export type Envelope<T> = SuccessEnvelope<T> | ErrorEnvelope;

export interface ChangeNotice {
  epoch: string;
  revision: number;
  domain: string;
  id?: string;
}
