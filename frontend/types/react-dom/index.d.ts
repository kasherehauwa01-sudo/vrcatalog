// Минимальные типы react-dom, достаточные для сборки приложения.
import type { ReactNode } from 'react';

export function createPortal(children: ReactNode, container: Element | DocumentFragment): ReactNode;
