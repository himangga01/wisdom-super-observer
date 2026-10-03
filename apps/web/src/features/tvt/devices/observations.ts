import type { DirectoryView } from '../../../lib/tvt/directory-api-client';

export type Observation = DirectoryView['records'][number];
export type ObservationName = Observation['fields'][number]['name'];
export type PageQuery = { page_num: number; page_size: number };
export type DirectoryReadState = { view?: DirectoryView; busy: boolean; error?: string; page?: PageQuery };
export const emptyRead: DirectoryReadState = { busy: false };

// Presentation only: the API client owns source whitelist and response validation.
export function field(record: Observation | undefined, name: ObservationName) {
  return record?.fields.find(item => item.name === name);
}
export function observed(record: Observation | undefined, name: ObservationName) {
  const item = field(record, name);
  return item?.state === 'value' && !item.opaque_kind ? item.value : undefined;
}
export function observationText(record: Observation | undefined, name: ObservationName): string {
  const value = observed(record, name);
  if (typeof value === 'string') return value || '값 없음';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? '예' : '아니요';
  return '확인할 수 없음';
}
export function objectObservation(record: Observation | undefined, name: ObservationName): Observation | undefined {
  const value = observed(record, name);
  return value && typeof value === 'object' && !Array.isArray(value) && 'fields' in value ? value : undefined;
}
export function listObservations(record: Observation | undefined, name: ObservationName): Observation[] {
  const value = observed(record, name);
  return Array.isArray(value) ? value.filter((item): item is Observation => Boolean(item && typeof item === 'object' && !Array.isArray(item) && 'fields' in item)) : [];
}
export function deviceSelector(record: Observation): string | undefined {
  const value = observed(record, 'sn');
  // The client validates syntax; selection never synthesizes or normalizes SN.
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}
export function channelSelector(record: Observation): number | undefined {
  const value = observed(record, 'chlIndex');
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 2147483647 ? value : undefined;
}
