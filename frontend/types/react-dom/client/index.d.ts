// Минимальные типы react-dom/client для React 18 createRoot.
import type { ReactNode } from 'react';

export interface Root {
  render(children: ReactNode): void;
  unmount(): void;
}

export function createRoot(container: Element | DocumentFragment): Root;
