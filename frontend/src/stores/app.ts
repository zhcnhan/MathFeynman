import { create } from "zustand";

// 前端状态骨架（docs/07 §4：Zustand）。M0 仅占位；M4 起承载会话/仪表盘状态。
interface AppState {
  serverOnline: boolean;
  setServerOnline: (v: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  serverOnline: false,
  setServerOnline: (v) => set({ serverOnline: v }),
}));
