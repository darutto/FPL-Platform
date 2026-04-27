import { redirect } from 'next/navigation';

/** Root redirects to the chat shell. Auth gating deferred to Phase 3. */
export default function HomePage() {
  redirect('/chat');
}
