import { addEventListener, definePlugin, openFilePicker, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaCompactDisc } from "react-icons/fa";
import { acknowledgeDump, cancelDump, checkUpdate, ejectDrive, emitProbeEvent, forceStopDump, getSnapshot, mountFilesystem, mountIso, ping, readRedumperVersion, startDump, unmountFilesystem, unmountIso, updateRedumper } from "./api/bridge";
import { requestDevelopmentInstall } from "./api/installUpdate";
import { subscribeChanged } from "./api/events";
import type { DiagnosticSnapshot } from "./api/types";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { actionNotice } from "./state/actionNotice";
import { chosenDumpFolder, dumpFolderRequest, publishDumpFolder, rejectedDumpFolderReason, rememberedDumpFolder, subscribeDumpFolder } from "./state/dumpRequest";
import { chosenIsoPath, isoPickerRequest } from "./state/isoPicker";
import { acceptSnapshot } from "./state/snapshotReducer";
import { updateNotice, type UpdateOffer } from "./state/updateNotice";

const refreshers = new Set<() => void>();

function Content() {
  const [snapshot, setSnapshot] = useState<DiagnosticSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);
  const [redumperMessage, setRedumperMessage] = useState<string | null>(null);
  const [updateOffer, setUpdateOffer] = useState<UpdateOffer | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingEjectId, setPendingEjectId] = useState<string | null>(null);
  const [imageName, setImageName] = useState("disc");
  const [outputRoot, setOutputRoot] = useState<string | null>(rememberedDumpFolder);
  const [pendingForceJobId, setPendingForceJobId] = useState<string | null>(null);
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

  useEffect(() => subscribeDumpFolder(setOutputRoot), []);

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
      updateMessage={updateMessage}
      updateOfferLabel={updateOffer?.label ?? null}
      redumperMessage={redumperMessage}
      onUpdateRedumper={() => {
        setBusy(true);
        void updateRedumper()
          .then((response) => {
            const notice = response.ok
              ? String(response.result.message ?? "Redumper was checked.")
              : `${response.code}: ${response.message}`;
            setRedumperMessage(notice);
            toaster.toast({ title: "Redumper", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "The Redumper update failed.";
            setRedumperMessage(notice);
            toaster.toast({ title: "Redumper", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onCheckUpdate={() => {
        setBusy(true);
        void checkUpdate()
          .then((response) => {
            if (!response.ok) {
              setUpdateOffer(null);
              setUpdateMessage(`${response.code}: ${response.message}`);
              return;
            }
            const notice = updateNotice(response.result);
            setUpdateMessage(notice.message);
            setUpdateOffer(notice.offer);
          })
          .catch((caught: unknown) => {
            setUpdateOffer(null);
            setUpdateMessage(caught instanceof Error ? caught.message : "The update check failed.");
          })
          .finally(() => {
            setBusy(false);
          });
      }}
      onInstallUpdate={() => {
        if (!updateOffer) {
          return;
        }
        setBusy(true);
        void requestDevelopmentInstall(updateOffer)
          .then(() => {
            const notice = `Confirm the Decky prompt to install version ${updateOffer.label}.`;
            setUpdateMessage(notice);
            toaster.toast({ title: "DiscDeck update", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "The update could not be requested.";
            setUpdateMessage(notice);
            toaster.toast({ title: "DiscDeck update", body: notice });
          })
          .finally(() => {
            setBusy(false);
          });
      }}
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
      imageName={imageName}
      onImageName={setImageName}
      outputRoot={outputRoot}
      pendingForceJobId={pendingForceJobId}
      onChooseDumpFolder={() => {
        setPendingEjectId(null);
        setBusy(true);
        const request = dumpFolderRequest(snapshot?.identity.home);
        void openFilePicker(
          request.select,
          request.startPath,
          request.includeFiles,
          request.includeFolders,
          undefined,
          undefined,
          request.showHiddenFiles,
          request.allowAllFiles,
        )
          .then((picked) => {
            const folder = chosenDumpFolder(picked);
            if (!folder) {
              const notice = rejectedDumpFolderReason(picked);
              setError(notice);
              toaster.toast({ title: "DiscDeck dump", body: notice });
              return;
            }
            publishDumpFolder(folder);
            toaster.toast({ title: "DiscDeck dump", body: `Dump folder set to ${folder}.` });
          })
          .catch((caught: unknown) => {
            const raw = caught instanceof Error ? caught.message : typeof caught === "string" ? caught : "The folder request failed.";
            const notice = raw === "User canceled" ? rejectedDumpFolderReason(null) : raw;
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .finally(() => {
            setBusy(false);
          });
      }}
      onDump={(driveId, generation) => {
        if (!outputRoot) {
          return;
        }
        setPendingEjectId(null);
        setBusy(true);
        void startDump(driveId, generation, imageName.trim() || "disc", outputRoot)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "The dump request failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onCancelDump={(jobId) => {
        setBusy(true);
        void cancelDump(jobId)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Cancel failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onForceDump={(jobId) => {
        const confirmed = pendingForceJobId === jobId;
        if (!confirmed) {
          setPendingForceJobId(jobId);
          const notice = "Press Confirm force stop. The process is still running.";
          setError(notice);
          toaster.toast({ title: "DiscDeck dump", body: notice });
          return;
        }
        setPendingForceJobId(null);
        setBusy(true);
        void forceStopDump(jobId, true)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "Force stop failed.";
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .finally(() => {
            setBusy(false);
            refresh();
          });
      }}
      onAcknowledgeDump={(jobId) => {
        setBusy(true);
        void acknowledgeDump(jobId)
          .then((response) => {
            const notice = actionNotice(response);
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
          })
          .catch((caught: unknown) => {
            const notice = caught instanceof Error ? caught.message : "The drive was not released.";
            setError(notice);
            toaster.toast({ title: "DiscDeck dump", body: notice });
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
