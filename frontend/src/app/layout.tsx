import type { Metadata } from 'next'
import './globals.css'
export const metadata: Metadata = { title: 'Incident Commander', description: 'Multi-Agent Incident Response' }
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>
}
