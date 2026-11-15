import SubscribeView from '@/components/subscribe/SubscribeView';
import { getRequestLocale } from '@/lib/i18n/server';

/** The membership page. The language is the request's (admin-only English while the rollout is `admin`). */
export default async function SubscribePage() {
  const { locale } = await getRequestLocale();
  return <SubscribeView locale={locale} />;
}
