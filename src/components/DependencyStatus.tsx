import { PanelSection, PanelSectionRow } from "@decky/ui";
import type { ModuleStatus } from "../api/types";
import { isProvenHardwareCapability } from "../state/proven";

export function DependencyStatus({ modules }: { modules: ModuleStatus[] }) {
  return (
    <PanelSection title="Modules">
      {modules.map((module) => (
        <PanelSectionRow key={module.id}>
          <div>
            {module.id}: {module.capability} / {module.effective}
            {module.reason_code ? ` (${module.reason_code})` : ""}
            {isProvenHardwareCapability(module) ? "" : " — not hardware-validated"}
          </div>
        </PanelSectionRow>
      ))}
    </PanelSection>
  );
}
