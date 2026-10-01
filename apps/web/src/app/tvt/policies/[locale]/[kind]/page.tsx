import { notFound } from "next/navigation";
import { PolicyReader } from "../../../../../features/tvt/policies/PolicyReader";
import { getPolicy, policyKinds, policyLocales } from "../../../../../features/tvt/policies/source";

// Let this specific route reject unknown parameters with notFound(). With false,
// Next skips unknown static parameters and falls through to /tvt/[[...path]].
export const dynamicParams = true;
export function generateStaticParams() {
  return policyLocales.flatMap(locale => policyKinds.map(kind => ({ locale, kind })));
}

export default async function PolicyPage({ params }: { params: Promise<{ locale: string; kind: string }> }) {
  const { locale, kind } = await params;
  const document = getPolicy(locale, kind);
  if (!document) notFound();
  return <PolicyReader document={document} />;
}
