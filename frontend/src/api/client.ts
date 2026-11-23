import {
  ConflictItem,
  DepletionProposal,
  EmailWorkerStatus,
  EventGeneratorItem,
  EventItem,
  GeneratorFeedbackItem,
  GeneratorRunItem,
  LearnedPromptRuleItem,
  PlaceItem,
  ProductItem,
  ProductUnitConversion,
  ShoppingListItem,
  StoreItemMultiplier,
  TripItem,
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

  const defaultTimeout = path.includes('/ingest/') ? 120000 : 30000;
  const signal = init?.signal || (typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal ? AbortSignal.timeout(defaultTimeout) : undefined);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal,
      credentials: 'include', // Guarantees 10-year HttpOnly cookie is always sent automatically!
      headers,
    });
  } catch (err: any) {
    const errStr = String(err?.message || err || '').toLowerCase();
    const isAbort =
      err?.name === 'AbortError' ||
      err?.name === 'TimeoutError' ||
      errStr.includes('abort') ||
      errStr.includes('timeout');

    if (isAbort) {
      if (path.includes('/ingest/upload')) {
        throw new ApiError(
          'Photo processing timed out. The Vision AI model took longer than 2 minutes to analyze the image. Please try again with a clearer or closer photo of just the receipt.',
          408
        );
      }
      throw new ApiError(
        'Request timed out. The server took longer than expected to respond. Please check your network connection and try again.',
        408
      );
    }

    const isNetworkError =
      err?.name === 'TypeError' ||
      errStr.includes('failed to fetch') ||
      errStr.includes('network') ||
      errStr.includes('load failed');

    if (isNetworkError) {
      throw new ApiError(
        'Unable to connect to the LiftAssistant server. Please verify the backend is running and reachable.',
        503
      );
    }

    throw new ApiError(
      err?.message || 'An unexpected error occurred while communicating with the server.',
      500
    );
  }

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
    let errMsg = data?.detail || data?.message || data?.error;
    if (Array.isArray(errMsg)) {
      errMsg = errMsg
        .map((e: any) => e.msg || e.message || (typeof e === 'string' ? e : JSON.stringify(e)))
        .join('; ');
    } else if (typeof errMsg === 'object' && errMsg !== null) {
      errMsg = errMsg.msg || errMsg.message || JSON.stringify(errMsg);
    }

    if (!errMsg || typeof errMsg !== 'string' || errMsg.trim() === '') {
      if (response.status === 413) {
        errMsg = 'The uploaded photo is too large for the server to process. Please try a smaller image.';
      } else if (response.status === 422) {
        errMsg = 'The receipt could not be parsed by the Vision model. Please ensure the receipt photo is clear and contains a visible store name, date, and total.';
      } else if (response.status === 504) {
        errMsg = 'Gateway timeout: Vision AI processing timed out on the server.';
      } else if (response.status === 500) {
        errMsg = 'Internal server error while processing the request. Please check the server logs.';
      } else {
        errMsg = `Request failed with status ${response.status}`;
      }
    }

    throw new ApiError(
      String(errMsg),
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
    studio: evt.studio || undefined,
    description: evt.description || evt.notes,
    dining_details: evt.dining_details || evt.dining_detail,
    shopping_details: evt.shopping_details || evt.shopping_detail,
    maintenance_details: evt.maintenance_details || evt.maintenance_detail,
    people_involved: Array.isArray(evt.people_involved) ? evt.people_involved : [],
    latitude: evt.latitude !== undefined && evt.latitude !== null ? Number(evt.latitude) : undefined,
    longitude: evt.longitude !== undefined && evt.longitude !== null ? Number(evt.longitude) : undefined,
    completed_at: evt.completed_at || undefined,
    created_at: evt.created_at || undefined,
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
  scheduled_end_at?: string;
  duration_minutes?: number;
  deadline?: string;
  completed_at?: string;
  place_id?: string;
  place_name?: string;
  studio?: string;
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
  studio?: string;
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

  /** List products in pantry inventory with live burn rates and computed days of runway. */
  async listProducts(limit = 100, offset = 0): Promise<ProductItem[]> {
    const raw = await requestJson<any>(`/inventory/products?limit=${limit}&offset=${offset}`);
    const items: any[] = Array.isArray(raw) ? raw : (raw?.result || raw?.items || []);
    return items.map((p) => ({
      ...p,
      name: p.name || p.product_name || 'Product',
      category: p.category || 'pantry',
      current_stock: p.current_stock !== undefined ? Number(p.current_stock) : 0,
      unit: p.unit || p.qu_stock_id || 'ea',
      purchase_unit: p.qu_purchase_id || p.purchase_unit || 'pack',
      unit_multiplier: p.qu_factor !== undefined ? Number(p.qu_factor) : (p.unit_multiplier || 1),
      daily_burn_rate: p.daily_burn_rate !== undefined ? Number(p.daily_burn_rate) : 0,
      days_runway: p.days_runway !== undefined ? Number(p.days_runway) : 999,
      store_name: p.store_name || 'Costco',
      location: p.location || 'Pantry',
      is_fridge_quick_tile: Boolean(p.is_fridge_quick_tile),
    }));
  },

  /** Decrement product stock via 1-tap fridge door pad. */
  async consumeProduct(productId: string, amount?: number): Promise<any> {
    return requestJson<any>(`/inventory/products/${encodeURIComponent(productId)}/consume`, {
      method: 'POST',
      body: JSON.stringify(amount !== undefined ? { amount } : {}),
    });
  },

  /** Undo accidental fridge pad tap. */
  async undoConsumeProduct(productId: string): Promise<any> {
    return requestJson<any>(`/inventory/products/${encodeURIComponent(productId)}/undo-consume`, {
      method: 'POST',
    });
  },

  /** List purchase-to-stock bulk multipliers. */
  async listConversions(): Promise<ProductUnitConversion[]> {
    const raw = await requestJson<any>('/inventory/conversions');
    return Array.isArray(raw) ? raw : (raw?.result || []);
  },

  /** List pending depletion proposals. */
  async listDepletions(): Promise<DepletionProposal[]> {
    const raw = await requestJson<any>('/inventory/proposals');
    const items: any[] = Array.isArray(raw) ? raw : (raw?.result || []);
    return items.map((d: any) => ({
      id: d.id,
      product_id: d.product_id,
      product_name: d.product_name || 'Pantry Item',
      proposed_deduction: Number(d.proposed_deduction ?? d.proposed_amount ?? d.amount ?? 1),
      unit: d.unit || 'ea',
      days_interval: d.days_interval !== undefined ? Number(d.days_interval) : 7,
      estimated_burn_rate: d.estimated_burn_rate || d.reason || `${d.proposed_deduction ?? d.proposed_amount ?? 1} ${d.unit || 'ea'} / wk`,
    }));
  },

  /** Confirm depletion proposal and deduct from stock ledger. */
  async confirmDepletion(proposalId: string): Promise<any> {
    return requestJson<any>(`/inventory/proposals/${encodeURIComponent(proposalId)}/confirm`, {
      method: 'POST',
    });
  },

  /** Dismiss depletion proposal without deducting stock. */
  async dismissDepletion(proposalId: string): Promise<any> {
    return requestJson<any>(`/inventory/proposals/${encodeURIComponent(proposalId)}/dismiss`, {
      method: 'POST',
    });
  },

  /** Fetch 7-day rolling horizon shopping list. */
  async listShoppingList(): Promise<ShoppingListItem[]> {
    const raw = await requestJson<any>('/shopping/shopping-list');
    const items: any[] = Array.isArray(raw) ? raw : (raw?.result || []);
    return items.map((it: any) => ({
      id: it.id,
      product_id: it.product_id,
      item_name: it.item_name || it.product_name || 'Item',
      category: it.category || 'grocery',
      amount: it.amount !== undefined ? Number(it.amount) : 1,
      unit: it.unit || 'ea',
      store_name: it.store_name || 'Costco',
      days_runway: it.days_runway !== undefined ? Number(it.days_runway) : 7,
      checked: Boolean(it.checked),
    }));
  },

  /** Toggle checked state of shopping list item. */
  async toggleShoppingItem(itemId: string): Promise<any> {
    return requestJson<any>(`/shopping/${encodeURIComponent(itemId)}/toggle`, {
      method: 'POST',
    });
  },

  /** List recurring event generators. */
  async listGenerators(): Promise<EventGeneratorItem[]> {
    const raw = await requestJson<any>('/generators');
    return Array.isArray(raw) ? raw : (raw?.result || []);
  },

  /** Create recurring event generator. */
  async createGenerator(payload: any): Promise<EventGeneratorItem> {
    return requestJson<EventGeneratorItem>('/generators', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Force spawn an event from a generator rule. */
  async spawnGenerator(genId: string): Promise<EventItem> {
    const raw = await requestJson<any>(`/generators/${encodeURIComponent(genId)}/spawn`, {
      method: 'POST',
    });
    return normalizeEventFromApi(raw);
  },

  /** List trips and their itinerary stops. */
  async listTrips(): Promise<TripItem[]> {
    const raw = await requestJson<any>('/trips');
    return Array.isArray(raw) ? raw : (raw?.result || []);
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
    existing_events?: GeneratorFeedbackItem[];
    feedbacks?: GeneratorFeedbackItem[];
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
  async triggerEmailGeneratorRun(maxResults = 25): Promise<{ run: GeneratorRunItem; summary_message: string }> {
    return requestJson<{ run: GeneratorRunItem; summary_message: string }>(`/generators/email/run?max_results=${maxResults}`, {
      method: 'POST',
    });
  },

  /** Trigger an immediate manual run of the Primrose School Lunch Menu Worker. */
  async triggerSchoolMenuWorkerRun(maxResults = 10): Promise<{ run: GeneratorRunItem; summary_message: string }> {
    return requestJson<{ run: GeneratorRunItem; summary_message: string }>(`/generators/school-menu/run?max_results=${maxResults}`, {
      method: 'POST',
    });
  },

  /** Directly parse school lunch menu text and generate meal switch reminders. */
  async parseSchoolMenuText(text: string, referenceDate?: string): Promise<{ created_count: number; events: any[]; summary_message: string }> {
    return requestJson<{ created_count: number; events: any[]; summary_message: string }>('/generators/school-menu/parse-text', {
      method: 'POST',
      body: JSON.stringify({ text, reference_date: referenceDate }),
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
    run_id?: string;
    feedback_id?: string;
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

  /** Upload a receipt file (image, PDF, JSON, text) to parse and create an event.
   * Only creates the event if parsing succeeds; throws error otherwise.
   */
  async uploadReceipt(file: File): Promise<{
    success: boolean;
    message: string;
    event: EventItem;
    receipt: any;
    job: any;
  }> {
    const formData = new FormData();
    formData.append('file', file);
    const timeoutSignal = typeof AbortSignal !== 'undefined' && 'timeout' in AbortSignal
      ? AbortSignal.timeout(120000)
      : undefined;
    const res = await requestJson<{
      success: boolean;
      message: string;
      event: any;
      receipt: any;
      job: any;
    }>('/ingest/upload', {
      method: 'POST',
      body: formData,
      signal: timeoutSignal,
    });
    return {
      ...res,
      event: normalizeEventFromApi(res.event),
    };
  },

  /** List all ingestion worker jobs and historical ingested receipts. */
  async getIngestionJobs(): Promise<any[]> {
    return requestJson<any[]>('/ingest/jobs');
  },
};

