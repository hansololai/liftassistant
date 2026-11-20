import {
  ConflictItem,
  EmailWorkerStatus,
  EventItem,
  GeneratorFeedbackItem,
  GeneratorRunItem,
  LearnedPromptRuleItem,
  PlaceItem,
  ProductItem,
  StoreItemMultiplier,
} from '../types';

const API_BASE = '/api/v1';

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const deviceToken = typeof window !== 'undefined' ? localStorage.getItem('lift_device_token') : null;
  const headers: Record<string, string> = {
    ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
    ...(deviceToken ? { 'X-Device-Token': deviceToken } : {}),
    ...(init?.headers as Record<string, string> || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    signal: init?.signal || (typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal ? AbortSignal.timeout(10000) : undefined),
    ...init,
    credentials: 'include', // Guarantees 10-year HttpOnly cookie is always sent automatically!
    headers,
  });

  const text = await response.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    const errMsg =
      data?.message ||
      data?.detail ||
      data?.error ||
      `Request failed with status ${response.status}`;
    throw new ApiError(
      typeof errMsg === 'string' ? errMsg : JSON.stringify(errMsg),
      response.status,
      data?.detail
    );
  }

  return data as T;
}

export function normalizeEventFromApi(raw: any): EventItem {
  const evt = raw?.event ? raw.event : raw;
  return {
    ...evt,
    place_name: evt.place_name || evt.place?.name,
    place_address: evt.place_address || evt.place?.address,
    description: evt.description || evt.notes,
    dining_details: evt.dining_details || evt.dining_detail,
    shopping_details: evt.shopping_details || evt.shopping_detail,
    maintenance_details: evt.maintenance_details || evt.maintenance_detail,
    people_involved: Array.isArray(evt.people_involved) ? evt.people_involved : [],
    latitude: evt.latitude !== undefined && evt.latitude !== null ? Number(evt.latitude) : undefined,
    longitude: evt.longitude !== undefined && evt.longitude !== null ? Number(evt.longitude) : undefined,
    completed_at: evt.completed_at || undefined,
  };
}

export interface CreatePlacePayload {
  name: string;
  address: string;
  category?: string;
  latitude?: number;
  longitude?: number;
  map_url?: string;
  google_place_id?: string;
  notes?: string;
}

export interface CreateScheduledEventPayload {
  title: string;
  event_type: string;
  scheduled_at?: string;
  duration_minutes?: number;
  deadline?: string;
  completed_at?: string;
  place_id?: string;
  place_name?: string;
  place_query?: string;
  latitude?: number;
  longitude?: number;
  people_involved?: string[];
  notes?: string;
  total_amount?: number;
}

export interface ConflictCheckPayload {
  scheduled_at: string;
  duration_minutes?: number;
  title?: string;
  people_involved?: string[];
  place_id?: string;
  notes?: string;
  event_id?: string;
}

export interface ConflictCheckResult {
  has_conflict: boolean;
  conflicts: Array<{
    id: string;
    event_id: string;
    event_title: string;
    conflict_type: string;
    severity: string;
    title: string;
    description: string;
    suggested_action: string;
    status: string;
  }>;
}

export interface CreateProductPayload {
  name: string;
  category?: string;
  qu_stock_id?: string;
  qu_purchase_id?: string;
  qu_factor?: number;
  initial_stock?: number;
  daily_burn_rate?: number;
  store_name?: string;
  receipt_raw_text?: string;
  is_fridge_quick_tile?: boolean;
  consume_step?: number;
  consume_step_label?: string;
  notes?: string;
}

export interface AuthStatusResult {
  authenticated: boolean;
  device_name: string | null;
  device_id: string | null;
}

export interface EnrollResult {
  success: boolean;
  device_id: string;
  device_name: string;
  session_token: string;
  message: string;
}

export interface DeviceItem {
  id: string;
  device_name: string;
  enroll_token: string;
  is_enrolled: boolean;
  enrolled_at: string | null;
  last_seen_at: string | null;
  user_agent: string | null;
  is_revoked: boolean;
  created_at: string;
}

export const apiClient = {
  /** Create a new product in pantry inventory with unit multiplier. */
  async createProduct(payload: CreateProductPayload): Promise<ProductItem> {
    return requestJson<ProductItem>('/inventory/products', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** List unit multipliers for (store, item, multiplier) 3-column table. */
  async listMultipliers(store?: string): Promise<StoreItemMultiplier[]> {
    const qs = store ? `?store=${encodeURIComponent(store)}` : '';
    return requestJson<StoreItemMultiplier[]>(`/inventory/multipliers${qs}`);
  },

  /** Upsert unit multiplier into 3-column table (store, item, multiplier). */
  async upsertMultiplier(payload: StoreItemMultiplier): Promise<StoreItemMultiplier> {
    return requestJson<StoreItemMultiplier>('/inventory/multipliers', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  /** List verified grounded places for autocomplete / select. */
  async listPlaces(search?: string): Promise<PlaceItem[]> {
    const qs = search ? `?search=${encodeURIComponent(search)}` : '';
    return requestJson<PlaceItem[]>(`/places${qs}`);
  },

  /** Search OpenStreetMap Nominatim & local cache for grounded physical places. */
  async searchPlaces(
    query: string,
    lat?: number,
    lng?: number,
    limit = 8
  ): Promise<PlaceItem[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    if (lat !== undefined && lng !== undefined) {
      params.set('lat', String(lat));
      params.set('lng', String(lng));
    }
    return requestJson<PlaceItem[]>(`/places/search?${params.toString()}`);
  },

  /** Ground and save a verified physical place into the permanent places catalog. */
  async createPlace(payload: CreatePlacePayload): Promise<PlaceItem> {
    return requestJson<PlaceItem>('/places', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** List events from backend ledger with pagination envelope and filter support. */
  async listEvents(filters?: { event_type?: string; status?: string; limit?: number; offset?: number }): Promise<EventItem[]> {
    const params = new URLSearchParams();
    if (filters?.event_type) params.set('event_type', filters.event_type);
    if (filters?.status) params.set('status', filters.status);
    if (filters?.limit) params.set('limit', String(filters.limit));
    if (filters?.offset) params.set('offset', String(filters.offset));
    const qs = params.toString() ? `?${params.toString()}` : '';

    const raw = await requestJson<any>(`/events${qs}`);
    const items: any[] = Array.isArray(raw) ? raw : (raw?.result || raw?.items || []);
    return items.map(normalizeEventFromApi);
  },

  /** Get a single event by ID. */
  async getEvent(eventId: string): Promise<EventItem> {
    const raw = await requestJson<any>(`/events/${encodeURIComponent(eventId)}`);
    return normalizeEventFromApi(raw);
  },

  /** Create a scheduled event via EventManager. */
  async createScheduledEvent(payload: CreateScheduledEventPayload): Promise<EventItem> {
    const raw = await requestJson<any>('/events', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return normalizeEventFromApi(raw);
  },

  /** Update an existing event in the ledger. */
  async updateEvent(eventId: string, payload: Partial<CreateScheduledEventPayload>): Promise<EventItem> {
    const raw = await requestJson<any>(`/events/${encodeURIComponent(eventId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    return normalizeEventFromApi(raw);
  },

  /** Mark an event as completed. */
  async completeEvent(eventId: string, completedAt?: string, totalAmount?: number): Promise<EventItem> {
    const raw = await requestJson<any>(`/events/${encodeURIComponent(eventId)}/complete`, {
      method: 'POST',
      body: JSON.stringify({ completed_at: completedAt, total_amount: totalAmount }),
    });
    return normalizeEventFromApi(raw);
  },

  /** Mark an event as incomplete / reopen. */
  async uncompleteEvent(eventId: string): Promise<EventItem> {
    const raw = await requestJson<any>(`/events/${encodeURIComponent(eventId)}/uncomplete`, {
      method: 'POST',
    });
    return normalizeEventFromApi(raw);
  },

  /** Pre-flight check for schedule, travel buffer, or facility conflicts. */
  async checkConflict(payload: ConflictCheckPayload): Promise<ConflictCheckResult> {
    try {
      const timeoutSignal = typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal ? AbortSignal.timeout(4000) : undefined;
      return await requestJson<ConflictCheckResult>('/events/check-conflict', {
        method: 'POST',
        body: JSON.stringify(payload),
        signal: timeoutSignal,
      });
    } catch (err) {
      console.warn('Conflict check request timed out or failed:', err);
      return { has_conflict: false, conflicts: [] };
    }
  },

  /** List all active conflicts across the schedule. */
  async listConflicts(): Promise<ConflictItem[]> {
    const raw = await requestJson<{ conflicts: ConflictItem[] }>('/events/conflicts');
    return raw.conflicts || [];
  },

  /** Recheck all schedule conflicts, optionally refreshing live external schedules (e.g. YMCA API). */
  async recheckConflicts(forceRefresh = true): Promise<{ conflicts: ConflictItem[]; message: string; total_conflicts: number }> {
    return requestJson<{ conflicts: ConflictItem[]; message: string; total_conflicts: number }>('/events/recheck-conflicts', {
      method: 'POST',
      body: JSON.stringify({ force_refresh: forceRefresh }),
    });
  },

  /** Resolve conflict via acknowledge or reschedule. */
  async resolveConflict(conflictId: string, action: 'ACKNOWLEDGE' | 'RESCHEDULE' = 'ACKNOWLEDGE'): Promise<any> {
    return requestJson<any>(`/events/conflicts/${encodeURIComponent(conflictId)}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
  },

  /** Exchange a one-time magic enrollment token for a permanent session token & cookie. */
  async enrollDevice(enrollToken: string): Promise<EnrollResult> {
    const res = await requestJson<EnrollResult>('/auth/enroll', {
      method: 'POST',
      body: JSON.stringify({ enroll_token: enrollToken }),
    });
    if (res.session_token && typeof window !== 'undefined') {
      localStorage.setItem('lift_device_token', res.session_token);
    }
    return res;
  },

  /** Check if the current device is authorized. */
  async checkAuthStatus(): Promise<AuthStatusResult> {
    return requestJson<AuthStatusResult>('/auth/status');
  },

  /** List authorized family devices. */
  async listDevices(): Promise<DeviceItem[]> {
    return requestJson<DeviceItem[]>('/auth/devices');
  },

  /** Generate a new device magic enrollment link. */
  async createDevice(deviceName: string): Promise<DeviceItem> {
    return requestJson<DeviceItem>('/auth/devices', {
      method: 'POST',
      body: JSON.stringify({ device_name: deviceName }),
    });
  },

  /** Revoke an authorized device immediately. */
  async revokeDevice(deviceId: string): Promise<{ success: boolean; message: string }> {
    return requestJson<{ success: boolean; message: string }>(`/auth/devices/${encodeURIComponent(deviceId)}/revoke`, {
      method: 'POST',
    });
  },

  /** Get email worker status and next scheduled run time. */
  async getEmailWorkerStatus(): Promise<EmailWorkerStatus> {
    return requestJson<EmailWorkerStatus>('/generators/email/worker');
  },

  /** List past email generator runs and execution results. */
  async listEmailGeneratorRuns(limit = 50): Promise<GeneratorRunItem[]> {
    return requestJson<GeneratorRunItem[]>(`/generators/email/runs?limit=${limit}`);
  },

  /** List history of runs across all worker types (Email, Depletion, Facility). */
  async listAllGeneratorRuns(generatorType?: string, limit = 50): Promise<GeneratorRunItem[]> {
    const q = generatorType ? `&generator_type=${encodeURIComponent(generatorType)}` : '';
    return requestJson<GeneratorRunItem[]>(`/generators/runs?limit=${limit}${q}`);
  },

  /** Get detailed execution outcome of a specific worker run (events for Email Worker, summary message for Depletion/Facility). */
  async getGeneratorRunResult(runId: string): Promise<{
    run: GeneratorRunItem;
    summary_message: string;
    events: GeneratorFeedbackItem[];
  }> {
    return requestJson(`/generators/runs/${encodeURIComponent(runId)}`);
  },

  /** Trigger an on-demand inventory depletion runway scan. */
  async triggerDepletionWorkerRun(): Promise<{ run: GeneratorRunItem; summary_message: string }> {
    return requestJson('/generators/depletion/run', { method: 'POST' });
  },

  /** Trigger an on-demand facility closure & conflict synchronization scan. */
  async triggerFacilityWorkerRun(): Promise<{ run: GeneratorRunItem; summary_message: string }> {
    return requestJson('/generators/facility/run', { method: 'POST' });
  },

  /** Trigger an on-demand recurring calendar rules evaluation. */
  async triggerCalendarRuleWorkerRun(): Promise<{ run: GeneratorRunItem; summary_message: string }> {
    return requestJson('/generators/calendar-rules/run', { method: 'POST' });
  },

  /** Trigger master orchestrator to run all 4 daily workers in sequence. */
  async triggerMasterDailyRun(): Promise<{ timestamp: string; run_type: string; success: boolean; failed_stages: string[]; results: Record<string, any> }> {
    return requestJson('/generators/master/run', { method: 'POST' });
  },

  /** Trigger master orchestrator to selectively retry only failed workers. */
  async triggerMasterRetryFailed(): Promise<{ retried_count: number; results: Record<string, any>; message: string }> {
    return requestJson('/generators/master/retry-failed', { method: 'POST' });
  },

  /** Trigger an immediate manual run of the Email Event Generator. */
  async triggerEmailGeneratorRun(maxResults = 25): Promise<GeneratorRunItem> {
    return requestJson<GeneratorRunItem>(`/generators/email/run?max_results=${maxResults}`, {
      method: 'POST',
    });
  },

  /** List events generated from email with AI perception reasoning and review feedback status. */
  async listGeneratedEmailEvents(limit = 100): Promise<GeneratorFeedbackItem[]> {
    return requestJson<GeneratorFeedbackItem[]>(`/generators/email/events?limit=${limit}`);
  },

  /** Submit review feedback for a generated event (Keep, Modify, or Remove with correction reason). */
  async submitEmailEventFeedback(payload: {
    event_id: string;
    status: 'ACCEPTED' | 'MODIFIED' | 'REMOVED';
    user_correction_reason?: string;
    modified_title?: string;
    modified_scheduled_at?: string;
    modified_amount?: number;
  }): Promise<{ success: boolean; status: string; event_id: string; feedback?: GeneratorFeedbackItem; learned_rule?: LearnedPromptRuleItem }> {
    return requestJson('/generators/email/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** List all active and archived learned prompt rules. */
  async listLearnedPromptRules(): Promise<LearnedPromptRuleItem[]> {
    return requestJson<LearnedPromptRuleItem[]>('/generators/email/rules');
  },

  /** Add a custom prompt instruction / rule. */
  async createLearnedPromptRule(payload: {
    user_feedback: string;
    prompt_instruction: string;
    rule_type?: 'NEGATIVE' | 'POSITIVE' | 'GENERAL';
  }): Promise<LearnedPromptRuleItem> {
    return requestJson<LearnedPromptRuleItem>('/generators/email/rules', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Toggle active status of a learned prompt rule. */
  async toggleLearnedPromptRule(ruleId: string, isActive: boolean): Promise<{ success: boolean; rule_id: string; is_active: boolean }> {
    return requestJson(`/generators/email/rules/${encodeURIComponent(ruleId)}/toggle?is_active=${isActive}`, {
      method: 'PUT',
    });
  },

  /** Delete a learned prompt rule. */
  async deleteLearnedPromptRule(ruleId: string): Promise<{ success: boolean; rule_id: string }> {
    return requestJson(`/generators/email/rules/${encodeURIComponent(ruleId)}`, {
      method: 'DELETE',
    });
  },

  /** Fetch current base and effective system prompt with dynamic learned rules. */
  async getEffectiveEmailPrompt(): Promise<{
    base_prompt: string;
    active_rules_count: number;
    active_rules: LearnedPromptRuleItem[];
    effective_prompt: string;
  }> {
    return requestJson('/generators/email/prompt');
  },
};

