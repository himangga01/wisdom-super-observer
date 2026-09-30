import { z } from "zod";
export const uuid = z.uuid();
export const connectionKinds = [
  "TVT_ACCOUNT",
  "TVT_DEVICE",
  "TYCO_ACCOUNT",
] as const;
export const kindLabel = {
  TVT_ACCOUNT: "TVT 계정",
  TVT_DEVICE: "TVT 기기",
  TYCO_ACCOUNT: "TYCO 계정",
};
const bounded = (max: number) =>
  z
    .string()
    .min(1)
    .max(max)
    .refine((value) => value.trim().length > 0);
const stores = z
  .array(uuid)
  .max(100)
  .refine((ids) => new Set(ids).size === ids.length);
const metadata = { alias: bounded(200), site: bounded(500), store_ids: stores };
const generation = { expected_generation: z.number().int().positive() };
const create = z
  .object({
    ...metadata,
    store_ids: stores.default([]),
    kind: z.enum(connectionKinds),
    username: bounded(512),
    password: bounded(4096),
  })
  .strict();
const patch = z
  .object({
    ...generation,
    alias: metadata.alias.optional(),
    site: metadata.site.optional(),
    store_ids: stores.optional(),
    username: bounded(512).optional(),
    password: bounded(4096).optional(),
  })
  .strict()
  .refine(
    (body) => (body.username === undefined) === (body.password === undefined),
  );
const revoke = z.object(generation).strict();
const publicSchema = z.object({
  id: uuid,
  tenant_id: uuid,
  kind: z.enum(connectionKinds),
  alias: metadata.alias,
  site: metadata.site,
  status: z.enum(["NOT_VERIFIED", "DISCONNECTED"]),
  last_success: z.string().datetime({ offset: true }).nullable(),
  generation: z.number().int().positive(),
  store_ids: stores,
});
export type ConnectionView = z.infer<typeof publicSchema>;
export function parseConnectionBody(
  action: "create" | "patch" | "revoke",
  body: unknown,
) {
  const result = { create, patch, revoke }[action].safeParse(body);
  if (!result.success) throw new Error("Invalid connection input");
  return result.data;
}
export function publicConnection(body: unknown): ConnectionView {
  const result = publicSchema.safeParse(body);
  if (!result.success) throw new Error("Invalid connection response");
  return result.data;
}
export const connectionMessage = (status: number) =>
  ({
    401: "로그인이 만료되었습니다. 다시 로그인하세요.",
    403: "연결 관리는 조직 소유자만 사용할 수 있습니다. 요청 권한을 확인하세요.",
    404: "연결이나 매장을 찾을 수 없습니다.",
    409: "다른 곳에서 연결이 변경되었습니다. 최신 내용을 확인한 뒤 다시 저장하세요.",
    422: "입력 내용을 확인하세요. 계정 교체 시 아이디와 비밀번호를 모두 입력하세요.",
    503: "연결을 저장하거나 불러올 수 없습니다. 잠시 후 다시 시도하세요.",
  })[status] ?? "요청을 완료할 수 없습니다. 잠시 후 다시 시도하세요.";
