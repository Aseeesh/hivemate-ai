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
export type Doc = { name: string; size: number; modified: string; audience?: 'public' | 'internal' };
export type Docs = { documents: Doc[]; lastSync: { status: string; startedAt: string } | null };
export type Audit = { SK: string; actor: string; action: string; at: number; detail: Record<string, unknown> };

export type ChatReply = { audience?: string; conversationId: string; reply: string; status: string; collected: Record<string, string>; complete: boolean };
export type Lead = { SK: string; convId: string; channel: string; customer: string; collected: Record<string, string>; status: string; handoffReason?: string; notes?: string; summary?: string; updatedAt: number };
export type Conv = { convId: string; channel: string; customer: string; status: string; collected: Record<string, string>; turns: number; lastAt: number; createdAt?: number };
export type ConvDetail = { conversation: Conv; turns: { role: string; text: string; at: number }[] };

export type PlatformTenant = { tenantId: string; name: string; createdAt: number | null; users: number; plugins: string[]; conversations: number; leads: number; leadsComplete: number; handoffs: number; messages: number; messagesHeld: number; lastActivity: number; channels: string[]; origins: string[] };
export type DayPoint = { day: string; conversations: number; leads: number };
export type PlatformOverview = { daily: DayPoint[]; tenants: number; users: number; conversations: number; leads: number; leadsComplete: number; handoffs: number; messages: number; messagesHeld: number; activeLast24h: number; pluginInstalls: Record<string, number>; truncated: boolean };
export type PlatformDetail = PlatformTenant & { daily: DayPoint[]; documentList: { name: string; size: number; modified: string }[]; userList: { email: string; role: string }[]; pluginList: { pluginId: string; version: string }[]; documents: { count: number; bytes: number }; recentAudit: { at: number; action: string }[] };

// ---- Hivemate 2.0: work queue, pipeline, impact, integrations ----
export type Task = { taskId: string; type: string; title: string; status: string; priority: 'urgent' | 'high' | 'normal'; detail: string; draft: string; dealId: string; to: string; subject: string; channel: string; action: string; createdAt: number; dueAt: number; assignee?: string; error?: string; sentVia?: string; bucket?: string; docId?: string };
export type WorkSummary = { open: number; needsApproval: number; failed: number; urgent: number; byType: Record<string, number> };
export type Work = { tasks: Task[]; summary: WorkSummary };
export type Deal = { dealId: string; source: string; name?: string; email?: string; phone?: string; need?: string; channel?: string; stage: string; awaiting: string; createdAt: number; lastInboundAt?: number; lastOutboundAt?: number; followUpCount: number; nextDueAt?: number; assignee?: string };
export type Policy = { modes: Record<string, 'assist' | 'approve' | 'automate'>; cadence: Record<string, number>; minutes: Record<string, number>; paused: Record<string, boolean>; sendWindow: { start: string; end: string } };
export type InboxRow = { kind: 'conversation' | 'email'; id: string; channel: string; title: string; preview: string; status: string; category: string; awaiting: string; stage: string; assignee: string; lastAt: number; dealId: string; unanswered: boolean };
export type Impact = { periodDays: number; measured: Record<string, number | null>; estimated: { minutesSaved: number; hoursSaved: number; note: string; basis: { type: string; count: number; minutesEach: number; minutes: number }[] }; notMeasured: string[]; daily: { day: string; tasks: number }[]; pipeline: Record<string, number> };
export type Connection = { provider: string; label: string; available: boolean; connected: boolean; status: string; account: string; lastSyncAt?: number; lastSyncStatus: string; lastError: string; failedEvents: number; tokenExpiresAt?: number; writes: string[] };
export type AskAnswer = { supported: boolean; answer: string; calculation: string; sources: { type: string; id: string; label: string }[]; examples?: string[] };
export type CustomerRow = { key: string; name: string; email: string; phone: string; stage: string; awaiting: string; deals: number; lastAt: number; channels: string[] };
export type CustomerDetail = Omit<CustomerRow, 'deals'> & { deals: Deal[]; conversations: { source: string; id: string; status: string; turns: number; lastAt: number; summary: string }[]; emails: { source: string; id: string; subject: string; status: string; category: string; at: number }[]; invoices: { source: string; id: string; number: string; amountDue: number; dueDate: string; status: string; daysOverdue: number }[]; outstandingFollowUps: { id: string; type: string; title: string; status: string; priority: string }[]; summary: string; summarySource: string; identity: string };
export type Pack = { id: string; name: string; blurb: string; enabled: boolean; planned: boolean; missing: string[] };
export type ExtractedDoc = { docId: string; fileName: string; status: string; flags: string[]; confidence: number; createdAt: number; supplier?: string; invoiceNumber?: string; invoiceDate?: string; dueDate?: string; subtotal?: number; gst?: number; total?: number };
