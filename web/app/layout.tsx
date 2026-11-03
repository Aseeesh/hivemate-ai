import './globals.css';
import type { ReactNode } from 'react';

export const metadata = { title: 'Hivemate', description: 'AI automation for New Zealand small businesses' };

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en-NZ"><body>{children}</body></html>;
}
