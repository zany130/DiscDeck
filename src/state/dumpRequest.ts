/** FileSelectionType.FOLDER from @decky/api. The published package does not export the enum value. */
export const PICK_FOLDER = 1;

export interface DumpFolderRequest {
  select: number;
  startPath: string;
  includeFiles: false;
  includeFolders: true;
  showHiddenFiles: false;
  allowAllFiles: true;
}

export function dumpFolderRequest(home: string | null | undefined): DumpFolderRequest {
  const startPath = typeof home === "string" && home.startsWith("/") ? home : "/";
  return {
    select: PICK_FOLDER,
    startPath,
    includeFiles: false,
    includeFolders: true,
    showHiddenFiles: false,
    allowAllFiles: true,
  };
}

let rememberedFolder: string | null = null;
const folderListeners = new Set<(folder: string | null) => void>();

export function rememberedDumpFolder(): string | null {
  return rememberedFolder;
}

export function publishDumpFolder(folder: string | null): void {
  rememberedFolder = folder;
  for (const listener of folderListeners) {
    listener(folder);
  }
}

export function subscribeDumpFolder(listener: (folder: string | null) => void): () => void {
  folderListeners.add(listener);
  listener(rememberedFolder);
  return () => {
    folderListeners.delete(listener);
  };
}

export function chosenDumpFolder(picked: { path?: string; realpath?: string } | string | null | undefined): string | null {
  for (const candidate of folderCandidates(picked)) {
    if (!candidate.toLowerCase().endsWith(".iso")) {
      return candidate;
    }
  }
  return null;
}

export function rejectedDumpFolderReason(picked: unknown): string {
  const candidates = folderCandidates(picked);
  if (candidates.length === 0) {
    return "The picker closed without a folder path. Open the folder, then press Select.";
  }
  return "That selection is an .iso file. Open the folder, then press Select.";
}

function folderCandidates(picked: unknown): string[] {
  if (typeof picked === "string") {
    const one = absoluteFolder(picked);
    return one ? [one] : [];
  }
  if (!picked || typeof picked !== "object") {
    return [];
  }
  const record = picked as { path?: unknown; realpath?: unknown };
  const found: string[] = [];
  for (const value of [record.realpath, record.path]) {
    const folder = absoluteFolder(value);
    if (folder && !found.includes(folder)) {
      found.push(folder);
    }
  }
  return found;
}

function absoluteFolder(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  let path = value.trim();
  if (path.startsWith("file://")) {
    path = path.slice("file://".length);
  }
  if (!path.startsWith("/")) {
    return null;
  }
  if (path.length > 1) {
    path = path.replace(/\/+$/, "");
  }
  return path;
}
