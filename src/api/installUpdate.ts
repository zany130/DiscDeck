import type { UpdateOffer } from "../state/updateNotice";

interface LoaderCall {
  call: (route: string, ...args: unknown[]) => Promise<unknown>;
}

/** Decky's store uses this route to raise the install prompt. Plugin `call` only reaches DiscDeck. */
function loaderCall(): LoaderCall["call"] | null {
  const backend = (window as Window & { DeckyBackend?: LoaderCall }).DeckyBackend;
  return backend && typeof backend.call === "function" ? backend.call.bind(backend) : null;
}

export async function requestDevelopmentInstall(offer: UpdateOffer): Promise<void> {
  const call = loaderCall();
  if (!call) {
    throw new Error("Decky did not expose plugin install. Use the development ZIP from the release page.");
  }
  await call("utilities/install_plugin", offer.artifactUrl, "DiscDeck", offer.version, offer.zipSha256, 2);
}
