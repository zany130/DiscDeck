export interface FeatureSettings {
  schema_version: number;
  settings_revision: number;
  modules: {
    "images.iso": boolean;
    "dump.redumper": boolean;
    "virtual.cdemu": boolean;
    "resources.pcgamingwiki": boolean;
    "launch.experimental": boolean;
    "launch.autoplay": boolean;
  };
}

export function defaultFeatureSettings(): FeatureSettings {
  return {
    schema_version: 1,
    settings_revision: 0,
    modules: {
      "images.iso": true,
      "dump.redumper": true,
      "virtual.cdemu": true,
      "resources.pcgamingwiki": true,
      "launch.experimental": false,
      "launch.autoplay": false,
    },
  };
}

export type EffectiveState = "active" | "disabled" | "unavailable" | "busy" | "disable_pending";

export function effectiveState(enabled: boolean, capability: string, operationActive: boolean): EffectiveState {
  if (!enabled && operationActive) {
    return "disable_pending";
  }
  if (!enabled) {
    return "disabled";
  }
  if (capability === "missing" || capability === "denied" || capability === "unsupported" || capability === "untested" || capability === "degraded") {
    return "unavailable";
  }
  if (capability === "ready" && operationActive) {
    return "busy";
  }
  if (capability === "ready") {
    return "active";
  }
  return "unavailable";
}
