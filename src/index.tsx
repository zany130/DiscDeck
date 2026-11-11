import { addEventListener, definePlugin, openFilePicker, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaCompactDisc } from "react-icons/fa";
import { ejectDrive, emitProbeEvent, getSnapshot, mountFilesystem, mountIso, ping, readRedumperVersion, unmountFilesystem, unmountIso } from "./api/bridge";
import { subscribeChanged } from "./api/events";
import type { DiagnosticSnapshot } from "./api/types";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { actionNotice } from "./state/actionNotice";
import { chosenIsoPath, isoPickerRequest } from "./state/isoPicker";
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
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck mount", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Mount failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck mount", body: notice });
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
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck unmount", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Unmount failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck unmount", body: notice });
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
          const notice = "Press Confirm eject. Nothing has been called yet.";
          setError(notice);
          toaster.toast({ title: "DiscDeck eject", body: notice });
          return;
        }
        setPendingEjectId(null);
        setBusy(true);
        void ejectDrive(driveId, generation, true)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck eject", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Eject failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck eject", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onPickIso={() => {
        setPendingEjectId(null);
        setBusy(true);
        const request = isoPickerRequest(snapshot?.identity.home);
        void openFilePicker(
          request.select,
          request.startPath,
          request.includeFiles,
          request.includeFolders,
          undefined,
          [...request.extensions],
          request.showHiddenFiles,
          request.allowAllFiles,
        )
          .then((picked) => {
            const path = chosenIsoPath(picked);
            if (!path) {
              return;
            }
            return mountIso(path).then((response) => {
              const notice = actionNotice(response);
              setError(notice);
              toaster.toast({ title: "DiscDeck ISO", body: notice });
            });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "The ISO request failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck ISO", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onUnmountIso={(imageId) => {
        setPendingEjectId(null);
        setBusy(true);
        void unmountIso(imageId)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck ISO", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Unmount failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck ISO", body: notice });
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
    if (notice.domain === "diagnostics") {
      toaster.toast({
        title: "DiscDeck probe",
        body: `revision ${notice.revision}`,
      });
    }
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
