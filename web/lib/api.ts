import { idToken } from './auth';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await idToken();
  if (!token) throw new ApiError(401, 'Signed out');
  const res = await fetch(process.env.NEXT_PUBLIC_API_URL + path, {
    method,
    headers: { authorization: `Bearer ${token}`, ...(body ? { 'content-type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string }).error ?? `Request failed (${res.status})`);
  return data as T;
}

export type Me = { user: { id: string; email: string; role: string; platform?: boolean }; tenant: { name: string; tenantId: string; currency: string; timezone: string } };
export type Plugin = { pluginId: string; name: string; version: string; category: string; description: string; permissions: string[]; events: string[]; installed: boolean; config?: Record<string, unknown>; configurationSchema: Record<string, { type: string; default: unknown }> };
export type Message = { SK: string; from: string; subject: string; body: string; category: string; confidence: number; draftReply: string; status: string; sendError?: string };
export type Doc = { name: string; size: number; modified: string };
export type Docs = { documents: Doc[]; lastSync: { status: string; startedAt: string } | null };
export type Audit = { SK: string; actor: string; action: string; at: number; detail: Record<string, unknown> };

export type ChatReply = { conversationId: string; reply: string; status: string; collected: Record<string, string>; complete: boolean };
export type Lead = { SK: string; convId: string; channel: string; customer: string; collected: Record<string, string>; status: string; handoffReason?: string; notes?: string; summary?: string; updatedAt: number };
export type Conv = { convId: string; channel: string; customer: string; status: string; collected: Record<string, string>; turns: number; lastAt: number };
export type ConvDetail = { conversation: Conv; turns: { role: string; text: string; at: number }[] };

export type PlatformTenant = { tenantId: string; name: string; createdAt: number | null; users: number; plugins: string[]; conversations: number; leads: number; leadsComplete: number; handoffs: number; messages: number; messagesHeld: number; lastActivity: number; channels: string[] };
export type PlatformOverview = { tenants: number; users: number; conversations: number; leads: number; leadsComplete: number; handoffs: number; messages: number; messagesHeld: number; activeLast24h: number; pluginInstalls: Record<string, number>; truncated: boolean };
export type PlatformDetail = PlatformTenant & { userList: { email: string; role: string }[]; pluginList: { pluginId: string; version: string }[]; documents: { count: number; bytes: number }; recentAudit: { at: number; action: string }[] };
