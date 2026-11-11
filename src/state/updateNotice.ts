export interface UpdateCheck {
  current_version?: string | null;
  current_commit?: string | null;
  remote_version?: string | null;
  remote_commit?: string | null;
  up_to_date?: boolean;
  artifact_url?: string | null;
  zip_sha256?: string | null;
}

export interface UpdateOffer {
  label: string;
  artifactUrl: string;
  version: string;
  zipSha256: string;
}

export function updateNotice(result: UpdateCheck): { message: string; offer: UpdateOffer | null } {
  const current = result.current_version || "an unpackaged build";
  if (result.up_to_date) {
    return { message: `Version ${current} is the latest development build.`, offer: null };
  }
  const remote = result.remote_version || (result.remote_commit ? result.remote_commit.slice(0, 7) : "a newer build");
  const artifactUrl = result.artifact_url;
  const zipSha256 = result.zip_sha256;
  if (!artifactUrl || !zipSha256) {
    return { message: `Version ${remote} is published. You are running ${current}.`, offer: null };
  }
  return {
    message: `Version ${remote} is published. You are running ${current}.`,
    offer: { label: remote, artifactUrl, version: result.remote_version || remote, zipSha256 },
  };
}

export function versionLabel(version: string | null | undefined, commit: string | null | undefined): string {
  const number = version || "unversioned";
  const build = commit ? commit.slice(0, 7) : "unpackaged";
  return `Version ${number} · build ${build}`;
}
