/** A hardware capability is proven only when a host gate explicitly says so. */

export function isProvenHardwareCapability(input: { capability?: string; hardware_validated?: boolean }): boolean {
  return input.capability === "ready" && input.hardware_validated === true;
}
