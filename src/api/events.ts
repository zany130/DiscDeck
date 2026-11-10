import type { ChangeNotice } from "./types";

export const CHANGED_EVENT = "discdeck:changed";

type AddListener = <Args extends unknown[] = []>(
  event: string,
  listener: (...args: Args) => void,
) => (...args: Args) => void;

type RemoveListener = <Args extends unknown[] = []>(
  event: string,
  listener: (...args: Args) => void,
) => void;

export function subscribeChanged(
  add: AddListener,
  remove: RemoveListener,
  listener: (notice: ChangeNotice) => void,
): () => void {
  const wrapped = add<[ChangeNotice]>(CHANGED_EVENT, (notice) => {
    listener(notice);
  });
  return () => {
    remove(CHANGED_EVENT, wrapped);
  };
}
