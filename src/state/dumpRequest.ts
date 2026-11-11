/** FileSelectionType.FOLDER from @decky/api. The published package does not export the enum value. */
export const PICK_FOLDER = 1;

export interface DumpFolderRequest {
  select: number;
  startPath: string;
  includeFiles: true;
  includeFolders: true;
  showHiddenFiles: false;
  allowAllFiles: true;
}

export function dumpFolderRequest(home: string | null | undefined): DumpFolderRequest {
  const startPath = typeof home === "string" && home.startsWith("/") ? home : "/";
  return {
    select: PICK_FOLDER,
    startPath,
    includeFiles: true,
    includeFolders: true,
    showHiddenFiles: false,
    allowAllFiles: true,
  };
}

export function chosenDumpFolder(picked: { path?: string; realpath?: string } | null | undefined): string | null {
  const realpath = picked?.realpath;
  if (typeof realpath === "string" && realpath.startsWith("/") && !realpath.endsWith(".iso")) {
    return realpath;
  }
  const path = picked?.path;
  if (typeof path === "string" && path.startsWith("/") && !path.endsWith(".iso")) {
    return path;
  }
  return null;
}
