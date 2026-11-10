import { addEventListener, definePlugin, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaCompactDisc } from "react-icons/fa";
import { emitProbeEvent, getSnapshot, ping, readRedumperVersion } from "./api/bridge";
import { subscribeChanged } from "./api/events";
import type { DiagnosticSnapshot } from "./api/types";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { acceptSnapshot } from "./state/snapshotReducer";

const refreshers = new Set<() => void>();

function Content() {
  const [snapshot, setSnapshot] = useState<DiagnosticSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const visible = useQuickAccessVisible();

  const refresh = () => {
    setBusy(true);
    void getSnapshot()
      .then((response) => {
        if (!response.ok) {
          setError(`${response.code}: ${response.message}`);
          return;
        }
        setSnapshot((current) => acceptSnapshot(current, response.result).snapshot);
        setError(null);
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : "The diagnostic call failed.");
      })
      .finally(() => {
        setBusy(false);
      });
  };

  useEffect(() => {
    refreshers.add(refresh);
    void ping().catch(() => undefined);
    refresh();
    return () => {
      refreshers.delete(refresh);
    };
  }, []);

  useEffect(() => {
    if (visible) {
      refresh();
    }
  }, [visible]);

  return (
    <DiagnosticsPanel
      snapshot={snapshot}
      busy={busy}
      error={error}
      onRefresh={refresh}
      onProbeEvent={() => {
        void emitProbeEvent();
      }}
      onVersionPolicy={() => {
        void readRedumperVersion(false).then((response) => {
          if (!response.ok) {
            setError(`${response.code}: ${response.message}`);
            return;
          }
          const reason = typeof response.result.reason_code === "string" ? response.result.reason_code : "untested";
          toaster.toast({ title: "Redumper version policy", body: reason });
        });
      }}
    />
  );
}

export default definePlugin(() => {
  const unsubscribe = subscribeChanged(addEventListener, removeEventListener, (notice) => {
    toaster.toast({
      title: "DiscDeck probe",
      body: `${notice.domain} revision ${notice.revision}`,
    });
    refreshers.forEach((refresh) => refresh());
  });

  return {
    name: "DiscDeck",
    titleView: <div className={staticClasses.Title}>DiscDeck</div>,
    content: <Content />,
    icon: <FaCompactDisc />,
    onDismount() {
      unsubscribe();
      refreshers.clear();
    },
  };
});
