import type { Metadata } from 'next';
import WcChatShell from '@/components/chat/WcChatShell';

export const metadata: Metadata = {
  title: 'Mundial 2026 Asistente',
  description: 'Asistente del Mundial 2026',
};

export default function WcChatPage() {
  return <WcChatShell />;
}
