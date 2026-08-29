import { create } from 'zustand';
import { Theme } from '../types';

interface ThemeState {
  theme: Theme;
  resolvedTheme: 'light' | 'dark';

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  initTheme: () => void;
}

const getSystemTheme = (): 'light' | 'dark' => {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: 'system',
  resolvedTheme: 'light',

  setTheme: (theme: Theme) => {
    localStorage.setItem('theme', theme);
    const resolved = theme === 'system' ? getSystemTheme() : theme;

    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(resolved);

    set({ theme, resolvedTheme: resolved });
  },

  toggleTheme: () => {
    const current = get().theme;
    const themes: Theme[] = ['light', 'dark', 'system'];
    const currentIndex = themes.indexOf(current);
    const nextTheme = themes[(currentIndex + 1) % themes.length];
    get().setTheme(nextTheme);
  },

  initTheme: () => {
    const saved = (localStorage.getItem('theme') as Theme) || 'system';
    get().setTheme(saved);

    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (get().theme === 'system') {
        get().setTheme('system');
      }
    });
  },
}));
