import { addEventListener, definePlugin, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaCompactDisc } from "react-icons/fa";
import { ejectDrive, emitProbeEvent, getSnapshot, mountFilesystem, ping, readRedumperVersion, unmountFilesystem } from "./api/bridge";
import { subscribeChanged } from "./api/events";
import type { DiagnosticSnapshot } from "./api/types";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { acceptSnapshot } from "./state/snapshotReducer";

const refreshers = new Set<() => void>();

function Content() {
  const [snapshot, setSnapshot] = useState<DiagnosticSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingEjectId, setPendingEjectId] = useState<string | null>(null);
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
      pendingEjectId={pendingEjectId}
      onMount={(driveId, generation, mediaGeneration) => {
        setPendingEjectId(null);
        setBusy(true);
        void mountFilesystem(driveId, generation, mediaGeneration)
          .then((response) => {
            if (!response.ok) {
              setError(`${response.code}: ${response.message}`);
              return;
            }
            setError(null);
            toaster.toast({ title: "DiscDeck mount", body: "Read-only mount was requested." });
          })
          .catch((caught: unknown) => {
            setError(caught instanceof Error ? caught.message : "Mount failed.");
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onUnmount={(driveId, generation) => {
        setPendingEjectId(null);
        setBusy(true);
        void unmountFilesystem(driveId, generation)
          .then((response) => {
            if (!response.ok) {
              setError(`${response.code}: ${response.message}`);
              return;
            }
            setError(null);
          })
          .catch((caught: unknown) => {
            setError(caught instanceof Error ? caught.message : "Unmount failed.");
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onEject={(driveId, generation) => {
        const confirmed = pendingEjectId === driveId;
        if (!confirmed) {
          setPendingEjectId(driveId);
          setError("Press Confirm eject to unmount this drive and eject it. Nothing has been called yet.");
          return;
        }
        setPendingEjectId(null);
        setBusy(true);
        void ejectDrive(driveId, generation, true)
          .then((response) => {
            if (!response.ok) {
              setError(`${response.code}: ${response.message}`);
              return;
            }
            setError(null);
            toaster.toast({ title: "DiscDeck eject", body: "UDisks2 eject was requested." });
          })
          .catch((caught: unknown) => {
            setError(caught instanceof Error ? caught.message : "Eject failed.");
          })
          .finally(() => {
            setBusy(false);
            refresh();
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
