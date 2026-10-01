import generated from "./generated-content.json";

export const policyLocales = ["en", "zh-Hans"] as const;
export const policyKinds = ["terms", "privacy"] as const;
export type PolicyLocale = typeof policyLocales[number];
export type PolicyKind = typeof policyKinds[number];
export type PolicyBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: PolicyBlock[][] }
  | { type: "table"; rows: PolicyBlock[][][] };
export type PolicyDocument = {
  locale: PolicyLocale;
  kind: PolicyKind;
  source_reference: string;
  source_sha256: string;
  source_bytes: number;
  content_sha256: string;
  blocks: PolicyBlock[];
};

// Bundled at build time: there is no runtime URL, filesystem or user source input.
const documents = generated.documents as PolicyDocument[];
export function getPolicy(locale: string, kind: string): PolicyDocument | undefined {
  if (!policyLocales.some(value => value === locale) || !policyKinds.some(value => value === kind)) return undefined;
  return documents.find(document => document.locale === locale && document.kind === kind);
}

export function policyRoute(locale: PolicyLocale, kind: PolicyKind): string {
  return `/tvt/policies/${locale}/${kind}`;
}
