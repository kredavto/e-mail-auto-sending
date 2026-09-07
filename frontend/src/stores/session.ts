import { create } from "zustand";

type SessionState = {
  workspaceId: string | null;
  setWorkspace: (id: string) => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  workspaceId: localStorage.getItem("workspace_id"),
  setWorkspace: (id) => {
    localStorage.setItem("workspace_id", id);
    set({ workspaceId: id });
  },
}));

