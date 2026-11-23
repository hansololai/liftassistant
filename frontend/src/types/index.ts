export type EventType = 'DINING' | 'SHOPPING' | 'MAINTENANCE' | 'MEDICAL' | 'TRAVEL' | 'CUSTOM';

export type SnapIntent = 'DINING' | 'SHOPPING' | 'MAINTENANCE' | 'MEDICAL' | 'TRAVEL' | 'CUSTOM';

export interface PlaceItem {
  id: string;
  name: string;
  category?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  map_url?: string;
  google_place_id?: string;
  notes?: string;
}

export interface EventItem {
  id: string;
  title: string;
  event_type: EventType;
  scheduled_at?: string;
  scheduled_end_at?: string;
  duration_minutes?: number;
  deadline?: string;
  completed_at?: string;
  created_at?: string;
  place_id?: string;
  studio?: string;
  latitude?: number;
  longitude?: number;
  place?: PlaceItem;
  place_name?: string;
  place_address?: string;
  people_involved: string[];
  description?: string;
  notes?: string;
  has_conflict?: boolean;
  conflict_status?: 'DETECTED' | 'ACKNOWLEDGED' | 'RESOLVED';
  conflict_reason?: string;
  dining_details?: {
    rating?: number;
    total_amount?: number;
  };
  shopping_details?: {
    store_name?: string;
    merchant_name?: string;
    merchant_address?: string;
    receipt_id?: string;
    receipt_image_path?: string;
    receipt_file_url?: string;
    original_filename?: string;
    pantry_updated?: boolean;
    subtotal?: number;
    tax_amount?: number;
    total_amount?: number;
    line_items?: any[];
  };
  maintenance_details?: {
    service_type?: string;
  };
}

export type ConflictType = 'FACILITY_MUTEX' | 'TRAVEL_BUFFER' | 'PERSON_OVERLAP' | 'POLICY_BLACKOUT';

export interface ConflictItem {
  id: string;
  event_id: string;
  event_title: string;
  conflict_type: ConflictType;
  severity: 'HIGH' | 'MEDIUM';
  title: string;
  description: string;
  suggested_action: string;
  status: 'DETECTED' | 'ACKNOWLEDGED' | 'RESOLVED';
}

export interface QuickTemplate {
  id: string;
  name: string;
  icon: string;
  default_category: EventType;
  default_person: string;
  default_people?: string[];
  default_duration_minutes: number;
  default_description: string;
  pinned: boolean;
  modal_type?: 'simple' | 'detailed' | 'smart_intake';
  default_place?: string;
  default_place_id?: string;
  default_studio?: string;
  default_coords?: { latitude: number; longitude: number };
}

export interface ProductItem {
  id: string;
  name: string;
  category: string;
  current_stock: number;
  unit: string;
  purchase_unit?: string;
  unit_multiplier?: number;
  consume_step?: number;
  consume_step_label?: string;
  daily_burn_rate: number;
  days_runway: number;
  store_name: string;
  location: string;
  is_fridge_quick_tile?: boolean;
}

export interface ProductUnitConversion {
  id: string;
  product_id: string;
  product_name: string;
  store_name: string;
  receipt_raw_text: string;
  purchase_unit: string;
  stock_unit: string;
  unit_multiplier: number;
}

export interface ShoppingListItem {
  id: string;
  product_id?: string;
  item_name: string;
  category: string;
  amount: number;
  unit: string;
  store_name: string;
  days_runway: number;
  checked: boolean;
}

export interface DepletionProposal {
  id: string;
  product_id: string;
  product_name: string;
  proposed_deduction: number;
  unit: string;
  days_interval: number;
  estimated_burn_rate: string;
}

export interface StoreItemMultiplier {
  store: string;
  item: string;
  multiplier: number;
  product_id?: string;
  product_name?: string;
}

export interface ExtractedLineItem {
  name: string;
  quantity: number;
  unit?: string;
  unit_price: number;
  total_price: number;
  grocy_product_id?: string;
  grocy_product_name?: string;
  unit_multiplier?: number;
  to_create_stock?: boolean;
}

export interface ReceiptJobResult {
  merchant_name: string;
  merchant_address?: string;
  place_id?: string;
  total_amount: number;
  subtotal?: number;
  tax_amount?: number;
  transaction_time: string;
  line_items_count: number;
  line_items?: ExtractedLineItem[];
}

export interface ReceiptJob {
  job_id: string;
  filename: string;
  file_hash: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  progress_pct: number;
  progress_message: string;
  created_at: string;
  is_confirmed?: boolean;
  result?: ReceiptJobResult;
}

export interface TripItem {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  budget: number;
  spent: number;
  stops: { name: string; date: string; spent: number }[];
}

export interface EventGeneratorItem {
  id: string;
  name: string;
  description?: string;
  event_type: EventType;
  recurrence_rule: 'YEARLY' | 'MONTHLY' | 'BI_WEEKLY' | 'WEEKLY' | 'CUSTOM_INTERVAL';
  target_month?: number;
  target_day?: number;
  target_weekday?: number; // 0=Sunday, 1=Monday, ..., 6=Saturday
  interval_days?: number;
  lead_time_days: number;
  deadline_offset_days: number;
  start_time?: string;
  duration_minutes?: number;
  is_active: boolean;
  last_generated_at?: string;
  next_target_date?: string;
}

export interface GeneratorRunItem {
  id: string;
  generator_type: string;
  started_at: string;
  completed_at?: string;
  status: 'RUNNING' | 'SUCCESS' | 'FAILED';
  scanned_count: number;
  created_count: number;
  error_message?: string;
  details_json?: string;
  event_ids?: string[];
  generated_events?: {
    id: string;
    title: string;
    event_type: string;
    scheduled_at?: string;
    deadline?: string;
    total_amount?: number;
    source?: string;
    notes?: string;
    llm_category?: string;
    llm_reason?: string;
    user_status?: string;
  }[];
}

export interface GeneratorFeedbackItem {
  id: string;
  event_id?: string;
  run_id?: string;
  source_reference_id?: string;
  email_subject?: string;
  email_from?: string;
  email_date?: string;
  llm_category?: string;
  llm_reason?: string;
  raw_json?: string;
  user_status: 'PENDING' | 'ACCEPTED' | 'MODIFIED' | 'REMOVED' | 'SKIPPED' | 'AUTOPAY_SKIPPED';
  user_correction_reason?: string;
  created_at: string;
  updated_at: string;
  event_title?: string;
  event_type?: string;
  total_amount?: number;
  scheduled_at?: string;
  deadline?: string;
  closure_facility_name?: string;
  closure_start?: string;
  closure_end?: string;
  closure_reason?: string;
  closure_facility_address?: string;
}

export interface LearnedPromptRuleItem {
  id: string;
  generator_type: string;
  rule_type: 'NEGATIVE' | 'POSITIVE' | 'GENERAL';
  user_feedback: string;
  prompt_instruction: string;
  is_active: boolean;
  created_at: string;
}

export interface EmailWorkerStatus {
  is_worker_running?: boolean;
  is_running?: boolean;
  is_syncing?: boolean;
  last_run_time?: string;
  next_run_time?: string;
  interval_seconds: number;
  workers?: Record<string, {
    latest_run_id?: string;
    latest_status?: string;
    latest_run_at?: string;
    created_count?: number;
    error_message?: string;
  }>;
}

export interface MasterDailyRunResult {
  timestamp: string;
  run_type: string;
  success: boolean;
  failed_stages: string[];
  results: Record<string, any>;
}


