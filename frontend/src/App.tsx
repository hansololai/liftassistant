import React, { useCallback, useEffect, useState } from 'react';
import {
  MantineProvider,
  AppShell,
  Group,
  Text,
  Badge,
  Container,
  ActionIcon,
  rem,
  Box,
  Notification,
  Transition,
  Indicator,
} from '@mantine/core';
import {
  IconSun,
  IconCalendar,
  IconShoppingCart,
  IconReceipt,
  IconPlane,
  IconCheck,
  IconSparkles,
  IconBell,
} from '@tabler/icons-react';
import {
  MOCK_CONFLICTS,
  MOCK_DEPLETIONS,
  MOCK_EVENTS,
  MOCK_GENERATORS,
  MOCK_PRODUCTS,
  MOCK_RECEIPT_JOBS,
  MOCK_SHOPPING_LIST,
  MOCK_TEMPLATES,
  MOCK_TRIPS,
  MOCK_CONVERSIONS,
  MOCK_STORE_ITEM_MULTIPLIERS,
} from './mockData';
import { apiClient } from './api/client';
import { TodayOverview } from './components/TodayOverview';
import { NotificationsView } from './components/NotificationsView';
import { EventsView } from './components/EventsView';
import { PantryView } from './components/PantryView';
import { ReceiptsView } from './components/ReceiptsView';
import { TripsView } from './components/TripsView';
import { EventModal } from './components/EventModal';
import { DeviceLockScreen } from './components/DeviceLockScreen';
import { FamilyDevicesModal } from './components/FamilyDevicesModal';
import {
  ConflictItem,
  DepletionProposal,
  EventGeneratorItem,
  EventItem,
  PlaceItem,
  ProductItem,
  ProductUnitConversion,
  StoreItemMultiplier,
  ReceiptJob,
  ShoppingListItem,
  SnapIntent,
} from './types';

export default function App() {
  const [activeTab, setActiveTab] = useState<'today' | 'notifications' | 'events' | 'pantry' | 'receipts' | 'trips'>('today');

  // Application State
  const [conflicts, setConflicts] = useState<ConflictItem[]>(MOCK_CONFLICTS);
  const [events, setEvents] = useState<EventItem[]>(MOCK_EVENTS);
  const [places, setPlaces] = useState<PlaceItem[]>([]);
  const [placesLoading, setPlacesLoading] = useState(false);
  const [depletions, setDepletions] = useState<DepletionProposal[]>(MOCK_DEPLETIONS);
  const [products, setProducts] = useState<ProductItem[]>(MOCK_PRODUCTS);
  const [conversions, setConversions] = useState<ProductUnitConversion[]>(MOCK_CONVERSIONS);
  const [multipliers, setMultipliers] = useState<StoreItemMultiplier[]>(MOCK_STORE_ITEM_MULTIPLIERS);
  const [generators, setGenerators] = useState<EventGeneratorItem[]>(MOCK_GENERATORS);
  const [shoppingList, setShoppingList] = useState<ShoppingListItem[]>(MOCK_SHOPPING_LIST);
  const [jobs, setJobs] = useState<ReceiptJob[]>(MOCK_RECEIPT_JOBS);
  const [notification, setNotification] = useState<string | null>(null);
  const [selectedEventForModal, setSelectedEventForModal] = useState<EventItem | null>(null);
  const [isRecheckingConflicts, setIsRecheckingConflicts] = useState(false);

  // Device Authentication State (Option 2: Magic Link Enrollment)
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [currentDeviceName, setCurrentDeviceName] = useState<string | null>(null);
  const [devicesModalOpened, setDevicesModalOpened] = useState(false);

  useEffect(() => {
    const initAuth = async () => {
      // 1. Check if opened with magic enrollment link: ?enroll_token=...
      const urlParams = new URLSearchParams(window.location.search);
      const enrollToken = urlParams.get('enroll_token') || urlParams.get('token');

      if (enrollToken) {
        try {
          const res = await apiClient.enrollDevice(enrollToken);
          if (res.success) {
            setAuthenticated(true);
            setCurrentDeviceName(res.device_name);
            showNotification(`Device Authorized: ${res.device_name}! Tap Share -> "Add to Home Screen".`);
            window.history.replaceState({}, document.title, window.location.pathname);
          }
        } catch (err: any) {
          console.warn('Auto enrollment failed:', err);
        }
      }

      // 2. Validate current device session
      try {
        const status = await apiClient.checkAuthStatus();
        setAuthenticated(status.authenticated);
        if (status.authenticated) {
          setCurrentDeviceName(status.device_name);
        }
      } catch (err) {
        console.warn('Could not check auth status:', err);
      } finally {
        setAuthChecked(true);
      }
    };

    void initAuth();
  }, []);

  const refreshMultipliers = useCallback(async () => {
    try {
      const list = await apiClient.listMultipliers();
      if (list && list.length > 0) {
        setMultipliers(list);
      }
    } catch (err) {
      console.warn('Could not load multipliers from API, keeping mock/local state:', err);
    }
  }, []);

  const refreshPlaces = useCallback(async () => {
    setPlacesLoading(true);
    try {
      const list = await apiClient.listPlaces();
      setPlaces(list);
    } catch (err) {
      console.warn('Could not load verified places from API:', err);
    } finally {
      setPlacesLoading(false);
    }
  }, []);

  const refreshEvents = useCallback(async () => {
    try {
      const list = await apiClient.listEvents();
      setEvents(list);
    } catch (err) {
      console.warn('Could not load events from API, keeping local state:', err);
    }
  }, []);

  const refreshConflicts = useCallback(async () => {
    try {
      const list = await apiClient.listConflicts();
      setConflicts(list);
    } catch (err) {
      console.warn('Could not load conflicts from API, keeping mock/local state:', err);
    }
  }, []);

  useEffect(() => {
    if (authenticated) {
      void refreshPlaces();
      void refreshEvents();
      void refreshMultipliers();
      void refreshConflicts();
    }
  }, [authenticated, refreshPlaces, refreshEvents, refreshMultipliers, refreshConflicts]);

  const handleUpsertMultiplier = (store: string, item: string, multiplier: number, productId?: string) => {
    const prod = products.find((p) => p.id === productId);
    const productName = prod ? prod.name : undefined;

    setMultipliers((prev) => {
      const idx = prev.findIndex(
        (m) => m.store.toLowerCase() === store.toLowerCase() && m.item.toLowerCase() === item.toLowerCase()
      );
      if (idx >= 0) {
        const copy = [...prev];
        copy[idx] = {
          store,
          item,
          multiplier,
          product_id: productId || copy[idx].product_id,
          product_name: productName || copy[idx].product_name,
        };
        return copy;
      }
      return [{ store, item, multiplier, product_id: productId, product_name: productName }, ...prev];
    });

    apiClient.upsertMultiplier({ store, item, multiplier, product_id: productId }).catch((err) => {
      console.warn('Could not persist multiplier to API:', err);
    });
  };

  // Unresolved items requiring user attention
  const activeJobs = jobs.filter((j) => j.status === 'PROCESSING' || j.status === 'PENDING');
  const unresolvedCount = conflicts.length + depletions.length + activeJobs.length;

  const showNotification = (msg: string) => {
    setNotification(msg);
    setTimeout(() => setNotification(null), 3500);
  };

  // Conflict Actions
  const handleResolveConflict = async (id: string) => {
    setConflicts((prev) => prev.filter((c) => c.id !== id));
    showNotification('Conflict acknowledged and kept on schedule.');
    try {
      await apiClient.resolveConflict(id, 'ACKNOWLEDGE');
      await refreshEvents();
    } catch (err) {
      console.warn('Could not acknowledge conflict via API:', err);
    }
  };

  const handleRescheduleConflict = async (id: string) => {
    setConflicts((prev) => prev.filter((c) => c.id !== id));
    showNotification('Event rescheduled! Conflict resolved.');
    try {
      await apiClient.resolveConflict(id, 'RESCHEDULE');
      await refreshEvents();
    } catch (err) {
      console.warn('Could not resolve conflict via API:', err);
    }
  };

  const handleRecheckConflicts = async () => {
    setIsRecheckingConflicts(true);
    try {
      const res = await apiClient.recheckConflicts(true);
      setConflicts(res.conflicts || []);
      await refreshEvents();
      if ((res.conflicts || []).length === 0) {
        showNotification('All clear! Zero schedule or facility conflicts detected.');
      } else {
        showNotification(`Rechecked schedule & YMCA API: ${res.conflicts.length} active conflict(s).`);
      }
    } catch (err) {
      console.warn('Conflict recheck failed:', err);
      showNotification('Rechecked conflicts against current schedule.');
    } finally {
      setIsRecheckingConflicts(false);
    }
  };

  const handleSaveEvent = async (updated: EventItem) => {
    setEvents((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    showNotification(`Saved changes to "${updated.title}".`);
    try {
      await apiClient.updateEvent(updated.id, {
        title: updated.title,
        event_type: updated.event_type,
        scheduled_at: updated.scheduled_at,
        deadline: updated.deadline,
        completed_at: updated.completed_at,
        place_id: updated.place_id,
        latitude: updated.latitude,
        longitude: updated.longitude,
        people_involved: updated.people_involved,
        notes: updated.description || updated.notes,
        total_amount: updated.shopping_details?.total_amount || updated.dining_details?.total_amount,
      });
      await refreshEvents();
    } catch (err) {
      console.warn('Could not persist event update to API:', err);
    }
  };

  const handleToggleComplete = async (eventId: string) => {
    const evt = events.find((e) => e.id === eventId);
    if (!evt) return;
    const isCompleted = !!evt.completed_at;
    const newCompletedAt = isCompleted ? undefined : new Date().toISOString();

    setEvents((prev) =>
      prev.map((e) => (e.id === eventId ? { ...e, completed_at: newCompletedAt } : e))
    );
    showNotification(isCompleted ? `Marked "${evt.title}" incomplete.` : `Completed "${evt.title}"!`);

    try {
      if (!isCompleted) {
        await apiClient.completeEvent(eventId);
      } else {
        await apiClient.uncompleteEvent(eventId);
      }
      await refreshEvents();
    } catch (err) {
      console.warn('Could not toggle event complete via API:', err);
    }
  };

  // Quick Event Actions
  const handleSaveQuickEvent = async (newEvent: Partial<EventItem>) => {
    const fullEvent: EventItem = {
      id: `evt_quick_${Date.now()}`,
      title: newEvent.title || 'Quick Event',
      event_type: newEvent.event_type || 'CUSTOM',
      scheduled_at: newEvent.scheduled_at || new Date().toISOString(),
      scheduled_end_at: newEvent.scheduled_end_at,
      completed_at: newEvent.completed_at || new Date().toISOString(),
      duration_minutes: newEvent.duration_minutes || 15,
      people_involved: newEvent.people_involved || ['Marcus'],
      description: newEvent.description || '',
      place_name: newEvent.place_name || 'Home (100 Main St, Cranberry Twp, PA)',
      latitude: newEvent.latitude,
      longitude: newEvent.longitude,
    };
    setEvents((prev) => [fullEvent, ...prev]);
    showNotification(`Logged "${fullEvent.title}" successfully!`);

    try {
      await apiClient.createScheduledEvent({
        title: fullEvent.title,
        event_type: fullEvent.event_type,
        scheduled_at: fullEvent.scheduled_at,
        completed_at: fullEvent.completed_at,
        duration_minutes: fullEvent.duration_minutes,
        people_involved: fullEvent.people_involved,
        notes: fullEvent.description,
        latitude: fullEvent.latitude,
        longitude: fullEvent.longitude,
      });
      await refreshEvents();
    } catch (err) {
      console.warn('Could not persist quick event to API:', err);
    }
  };

  // Dedicated Page 2 Event Action (Awaited server confirmation & invalidation)
  const handleAddEvent = async (newEvent: EventItem) => {
    const created = await apiClient.createScheduledEvent({
      title: newEvent.title,
      event_type: newEvent.event_type,
      scheduled_at: newEvent.scheduled_at,
      duration_minutes: newEvent.duration_minutes || 60,
      deadline: newEvent.deadline,
      place_id: newEvent.place_id,
      people_involved: newEvent.people_involved,
      notes: newEvent.description || newEvent.notes,
    });
    await refreshEvents();
    showNotification(`Added "${created.title}" to calendar.`);
  };

  // Event Generator Actions (Awaited server confirmation & invalidation)
  const handleAddGenerator = async (newGen: EventGeneratorItem) => {
    await new Promise((r) => setTimeout(r, 600));
    setGenerators((prev) => [newGen, ...prev]);
    showNotification(`Recurring generator "${newGen.name}" saved!`);
  };

  const handleRunGenerator = (genId: string) => {
    const gen = generators.find((g) => g.id === genId);
    if (!gen) return;

    // Calculate target & deadline date
    const now = new Date();
    const currentYear = now.getFullYear();
    let targetDate = new Date();

    if (gen.recurrence_rule === 'YEARLY') {
      const targetMonth = gen.target_month ? gen.target_month - 1 : now.getMonth();
      const targetDay = gen.target_day || 15;
      targetDate = new Date(currentYear, targetMonth, targetDay, 23, 59, 59);
      if (targetDate.getTime() < now.getTime() - 24 * 3600 * 1000) {
        targetDate = new Date(currentYear + 1, targetMonth, targetDay, 23, 59, 59);
      }
    } else if (gen.recurrence_rule === 'MONTHLY') {
      const targetDay = gen.target_day || 15;
      targetDate = new Date(currentYear, now.getMonth(), targetDay, 23, 59, 59);
      if (targetDate.getTime() < now.getTime() - 24 * 3600 * 1000) {
        targetDate = new Date(currentYear, now.getMonth() + 1, targetDay, 23, 59, 59);
      }
    } else if (gen.recurrence_rule === 'WEEKLY' || gen.recurrence_rule === 'BI_WEEKLY') {
      const targetWeekday = gen.target_weekday !== undefined ? gen.target_weekday : 1; // 1 = Monday
      const currentDay = now.getDay();
      let diff = (targetWeekday - currentDay + 7) % 7;
      if (diff === 0) diff = gen.recurrence_rule === 'BI_WEEKLY' ? 14 : 7;
      targetDate = new Date(now.getTime() + diff * 24 * 3600 * 1000);
      targetDate.setHours(23, 59, 59, 0);
    }

    const scheduledDate = new Date(targetDate.getTime() - gen.lead_time_days * 24 * 3600 * 1000);
    const [startHour, startMin] = (gen.start_time || '09:00').split(':').map((s) => parseInt(s, 10));
    scheduledDate.setHours(startHour, startMin, 0, 0);

    const durationMins = gen.duration_minutes || 60;
    const scheduledEndDate = new Date(scheduledDate.getTime() + durationMins * 60000);
    const deadlineDate = new Date(targetDate.getTime() + gen.deadline_offset_days * 24 * 3600 * 1000);

    const generatedEvent: EventItem = {
      id: `evt_spawn_${Date.now()}`,
      title: gen.name,
      event_type: gen.event_type,
      scheduled_at: scheduledDate.toISOString(),
      scheduled_end_at: scheduledEndDate.toISOString(),
      deadline: deadlineDate.toISOString(),
      place_name: 'Cranberry Twp, PA',
      people_involved: ['Dad'],
      description: `Auto-generated from rule "${gen.name}". Lead time: ${gen.lead_time_days}d. Duration: ${durationMins}m. Due: ${deadlineDate.toLocaleDateString()}`,
    };

    setEvents((prev) => [generatedEvent, ...prev]);
    showNotification(`Spawned "${gen.name}" with deadline ${deadlineDate.toLocaleDateString()}!`);
  };

  // Unified Multi-Intent Intake Actions with User-Filled Context & Deferred AI Refinement
  const handleSnapReceipt = (
    intent: SnapIntent,
    details?: Partial<EventItem>,
    customFilename?: string,
    formatType?: 'PHOTO' | 'JSON' | 'PDF' | 'CSV'
  ) => {
    const eventId = `evt_snap_${Date.now()}`;

    // Helper default titles & filenames per intent
    const getDefaultTitle = () => {
      switch (intent) {
        case 'DINING': return 'Dining Out';
        case 'SHOPPING': return 'Store Restock';
        case 'MAINTENANCE': return 'Vehicle Maintenance';
        case 'MEDICAL': return 'Medical Visit';
        case 'TRAVEL': return 'Travel / Gas Stop';
        default: return 'Expense / Record';
      }
    };

    const getFilename = () => {
      if (customFilename) return customFilename;
      if (formatType === 'JSON') return 'costco-receipts-09-30-2026-10-02-2026.json';
      const cleanTitle = details?.title ? details.title.toLowerCase().replace(/[^a-z0-9]/g, '_') : intent.toLowerCase();
      switch (intent) {
        case 'DINING': return `${cleanTitle}_receipt.jpg`;
        case 'SHOPPING': return 'costco_grocery_receipt.jpg';
        case 'MAINTENANCE': return 'valvoline_invoice.pdf';
        case 'MEDICAL': return 'pediatric_clinic_summary.pdf';
        case 'TRAVEL': return 'sheetz_gas_receipt.jpg';
        default: return 'receipt_document.jpg';
      }
    };

    const getProgressMessage = () => {
      if (formatType === 'JSON' || (customFilename && customFilename.endsWith('.json'))) {
        return 'Parsing structured JSON warehouse receipt payload & grounding place...';
      }
      switch (intent) {
        case 'DINING': return 'Scanning receipt header: Searching printed merchant name & street address...';
        case 'SHOPPING': return 'Reconciling line items with Grocy pantry inventory ledger...';
        case 'MAINTENANCE': return 'Extracting vehicle service checklist, labor, parts & odometer record...';
        case 'MEDICAL': return 'Extracting provider address, diagnosis notes & co-pay receipt...';
        default: return 'Extracting merchant, address, date and total amount...';
      }
    };

    // 1. If details provided by modal, create the completed Event record immediately with user's initial location & time
    if (details) {
      const fullEvent: EventItem = {
        id: eventId,
        title: details.title || getDefaultTitle(),
        event_type: intent,
        completed_at: details.completed_at || new Date().toISOString(),
        scheduled_at: details.scheduled_at || new Date().toISOString(),
        scheduled_end_at: details.scheduled_end_at || new Date().toISOString(),
        place_name: details.place_name || 'Current Location (Nearby)',
        people_involved: details.people_involved || ['Family'],
        description: details.description || '',
        dining_details: details.dining_details,
        shopping_details: details.shopping_details,
        maintenance_details: details.maintenance_details,
      };
      setEvents((prev) => [fullEvent, ...prev]);
    }

    // 2. Launch background ingestion job
    const newJob: ReceiptJob = {
      job_id: `job_rec_${Date.now()}`,
      filename: getFilename(),
      file_hash: `sha_${Math.random().toString(36).substring(2, 10)}...`,
      status: 'PROCESSING',
      progress_pct: 35,
      progress_message: getProgressMessage(),
      created_at: new Date().toISOString(),
      is_confirmed: false,
    };
    setJobs((prev) => [newJob, ...prev]);

    const titleMsg = details?.title || getDefaultTitle();
    const peopleMsg = details?.people_involved?.join(', ') || 'Family';

    const getSubmitNotification = () => {
      if (!details) {
        return `📄 Uploaded "${newJob.filename}"! Processing background parsing job.`;
      }
      switch (intent) {
        case 'DINING': return `📸 "${titleMsg}" saved with ${peopleMsg}! AI extracting merchant address & totals.`;
        case 'SHOPPING': return `🛒 "${titleMsg}" saved! Pantry restock processing in background.`;
        case 'MAINTENANCE': return `🔧 "${titleMsg}" saved! Extracting vehicle service & shop address in background.`;
        case 'MEDICAL': return `🩺 "${titleMsg}" saved for ${peopleMsg}! Extracting clinic address & summary in background.`;
        default: return `📄 "${titleMsg}" saved! Processing document in background.`;
      }
    };
    showNotification(getSubmitNotification());

    // 3. Simulate async completion & smart address / data refinement after 2.8s
    setTimeout(() => {
      const isCostcoJson = formatType === 'JSON' || newJob.filename.includes('costco-receipts') || newJob.filename.toLowerCase().endsWith('.json');

      let aiMerchant = 'Mad Mex Cantina';
      let aiAddress = 'Mad Mex, 20510 Rte 19, Cranberry Twp, PA';
      let aiPlaceId: string | undefined = undefined;
      let aiTotal = 58.5;
      let aiSubtotal = 58.5;
      let aiTax = 0.0;
      let aiTransactionTime = new Date().toLocaleDateString();
      let aiItemsCount = 3;
      let aiLineItems: any[] | undefined = undefined;
      let aiUpdatedTitle = details?.title || 'Dinner at Mad Mex';

      if (isCostcoJson) {
        aiMerchant = 'Costco Wholesale #328 (Cranberry Twp)';
        aiAddress = '1050 CRANBERRY SQUARE DR, CRANBERRY TOWNS, PA, 16066, US';
        aiPlaceId = 'pl_costco';
        aiTotal = 125.27;
        aiSubtotal = 125.27;
        aiTax = 0.0;
        aiTransactionTime = '2026-10-02 20:24:00';
        aiItemsCount = 9;
        aiUpdatedTitle = 'Costco Wholesale Restock';
        aiLineItems = [
          { name: 'Kiwi Berries, 1 lb', quantity: 2, unit: 'pk', unit_price: 6.99, total_price: 13.98 },
          { name: 'KS KS PRK BELLY', quantity: 6.78, unit: 'lb', unit_price: 3.99, total_price: 27.05 },
          { name: 'Kirkland Signature Seasoned Chicken Wings', quantity: 1, unit: 'ea', unit_price: 17.51, total_price: 17.51 },
          { name: 'ORG A2 WHOLE MILK 3-PK', quantity: 1, unit: 'ea', unit_price: 11.79, total_price: 11.79, grocy_product_id: 'prod_milk', grocy_product_name: 'Organic Whole Milk' },
          { name: 'KS PAPER TOWELS', quantity: 1, unit: 'ea', unit_price: 22.99, total_price: 22.99 },
          { name: 'CJ BULGOGI MANDU', quantity: 1, unit: 'ea', unit_price: 14.99, total_price: 14.99 },
          { name: '/ 1785501 Instant Savings', quantity: 1, unit: 'ea', unit_price: -4.50, total_price: -4.50 },
          { name: 'HAITAI CRUNCH BON', quantity: 1, unit: 'ea', unit_price: 10.99, total_price: 10.99 },
          { name: 'KS CASHEWS', quantity: 1, unit: 'ea', unit_price: 15.47, total_price: 15.47 },
        ];
      } else if (intent === 'DINING') {
        aiMerchant = 'Mad Mex Cantina';
        aiAddress = 'Mad Mex, 20510 Rte 19, Cranberry Twp, PA';
        aiTotal = 58.5;
        aiSubtotal = 55.0;
        aiTax = 3.5;
        aiUpdatedTitle = 'Dinner at Mad Mex';
      } else if (intent === 'SHOPPING') {
        aiMerchant = 'Costco Wholesale #1024';
        aiAddress = 'Costco Wholesale, 1050 Cranberry Square Dr, Cranberry Twp, PA';
        aiPlaceId = 'pl_costco';
        aiTotal = 142.1;
        aiSubtotal = 142.1;
        aiTax = 0.0;
        aiUpdatedTitle = 'Costco Wholesale Restock';
        aiItemsCount = 14;
        aiLineItems = [
          { name: 'Organic Bananas, 3 lb', quantity: 1, unit: 'bunch', unit_price: 1.99, total_price: 1.99 },
          { name: 'Organic Whole Milk (1 Gal)', quantity: 2, unit: 'gal', unit_price: 4.49, total_price: 8.98, grocy_product_id: 'prod_milk', grocy_product_name: 'Organic Whole Milk' },
          { name: 'Kirkland Paper Towels', quantity: 1, unit: 'pack', unit_price: 22.99, total_price: 22.99, grocy_product_id: 'prod_paper_towels', grocy_product_name: 'Paper Towels' },
        ];
      } else if (intent === 'MAINTENANCE') {
        aiMerchant = 'Valvoline Instant Oil Change';
        aiAddress = 'Valvoline Instant Oil Change, 20120 Rte 19, Cranberry Twp, PA';
        aiTotal = 89.99;
        aiSubtotal = 89.99;
        aiTax = 0.0;
        aiUpdatedTitle = 'Honda Odyssey Maintenance (Valvoline)';
      } else if (intent === 'MEDICAL') {
        aiMerchant = 'UPMC Children’s Community Pediatrics';
        aiAddress = 'UPMC Children’s Pediatrics, 118 Towne Center Dr, Wexford, PA';
        aiTotal = 35.0;
        aiSubtotal = 35.0;
        aiTax = 0.0;
        aiUpdatedTitle = 'Marcus Pediatric Checkup';
      } else {
        aiMerchant = 'Sheetz Convenience #452';
        aiAddress = 'Sheetz #452, 20110 Route 19, Cranberry Twp, PA';
        aiTotal = 45.2;
        aiSubtotal = 45.2;
        aiTax = 0.0;
        aiUpdatedTitle = details?.title || 'Sheetz Fuel & Travel Stop';
      }

      setJobs((prev) =>
        prev.map((j) =>
          j.job_id === newJob.job_id
            ? {
                ...j,
                status: 'COMPLETED',
                progress_pct: 100,
                progress_message: 'Complete! Place grounded & ready for review.',
                is_confirmed: false,
                result: {
                  merchant_name: aiMerchant,
                  merchant_address: aiAddress,
                  place_id: aiPlaceId,
                  total_amount: aiTotal,
                  subtotal: aiSubtotal,
                  tax_amount: aiTax,
                  transaction_time: aiTransactionTime,
                  line_items_count: aiItemsCount,
                  line_items: aiLineItems,
                },
              }
            : j
        )
      );

      // Refine existing event if one was created upfront (Snap & Go preset modal)
      if (details) {
        setEvents((prev) =>
          prev.map((e) =>
            e.id === eventId
              ? {
                  ...e,
                  title: aiUpdatedTitle,
                  place_name: aiAddress,
                  ...(intent === 'DINING' ? { dining_details: { ...e.dining_details, total_amount: aiTotal } } : {}),
                  ...(intent === 'SHOPPING' ? { shopping_details: { ...e.shopping_details, total_amount: aiTotal } } : {}),
                }
              : e
          )
        );
        showNotification(
          `✨ AI discovered address: "${aiAddress}" (\$${aiTotal.toFixed(2)}) and refined event!`
        );
      } else {
        // Pure Approach 2 upload: user can now click Check & Confirm in Receipts tab
        showNotification(
          `✨ Ingestion complete for "${aiMerchant}" (\$${aiTotal.toFixed(2)})! Click "Check & Confirm" to log event.`
        );
      }
    }, 2800);
  };

  // Approach 2: Check & Confirm Receipt Action
  const handleConfirmReceiptJob = (job: ReceiptJob, people: string[], updatePantry: boolean) => {
    // 1. Mark job as confirmed in jobs state
    setJobs((prev) =>
      prev.map((j) => (j.job_id === job.job_id ? { ...j, is_confirmed: true } : j))
    );

    // 2. Extract details
    const merchantName = job.result?.merchant_name || 'Costco Wholesale';
    const placeId = job.result?.place_id || 'pl_costco';
    const placeAddress = job.result?.merchant_address || '1050 Cranberry Square Dr, Cranberry Twp, PA';
    const totalAmount = job.result?.total_amount || 0;
    const transactionTime = job.result?.transaction_time || new Date().toISOString();

    // 3. Create the shopping event record
    const shoppingEvent: EventItem = {
      id: `evt_shop_${Date.now()}`,
      title: merchantName,
      event_type: 'SHOPPING',
      place_id: placeId,
      place_name: merchantName,
      place_address: placeAddress,
      completed_at: transactionTime,
      scheduled_at: transactionTime,
      scheduled_end_at: transactionTime,
      people_involved: people.length > 0 ? people : ['Family'],
      description: `Ingested & confirmed via Approach 2 from ${job.filename}. Total: $${totalAmount.toFixed(2)} (${job.result?.line_items_count || 0} line items).`,
      shopping_details: {
        store_name: merchantName,
        total_amount: totalAmount,
        pantry_updated: updatePantry,
        line_items: job.result?.line_items?.map((it) => ({
          product_name: it.name,
          quantity: it.quantity,
          unit: it.unit || 'unit',
          unit_price: it.unit_price,
          total_price: it.total_price,
          grocy_product_id: it.grocy_product_id,
        })),
      },
    };

    setEvents((prev) => [shoppingEvent, ...prev]);

    // 4. Update pantry stock & check off shopping list if requested
    if (updatePantry && job.result?.line_items) {
      const lineItems = job.result.line_items;
      const newlyCreatedProducts: ProductItem[] = [];

      // Auto-create stock products for items marked to_create_stock
      lineItems.forEach((it) => {
        if (it.to_create_stock && !it.grocy_product_id && it.total_price >= 0) {
          const mult = it.unit_multiplier || 1.0;
          const unitsAdded = parseFloat(((it.quantity || 1) * mult).toFixed(2));
          const prodId = `prod_auto_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;

          const newProduct: ProductItem = {
            id: prodId,
            name: it.name,
            category: 'Pantry',
            unit: it.unit || 'unit',
            purchase_unit: 'pack',
            unit_multiplier: mult,
            current_stock: unitsAdded,
            daily_burn_rate: 0.1,
            days_runway: unitsAdded > 0 ? parseFloat((unitsAdded / 0.1).toFixed(1)) : 999,
            store_name: merchantName,
            location: 'Pantry',
            is_fridge_quick_tile: false,
          };
          newlyCreatedProducts.push(newProduct);

          // Upsert multiplier into (store, item, multiplier, product_id) table
          handleUpsertMultiplier(merchantName, it.name, mult, prodId);

          // Persist product to backend API
          apiClient
            .createProduct({
              name: it.name,
              category: 'Pantry',
              qu_stock_id: it.unit || 'unit',
              qu_purchase_id: 'pack',
              qu_factor: mult,
              initial_stock: unitsAdded,
              daily_burn_rate: 0.1,
              store_name: merchantName,
              receipt_raw_text: it.name,
            })
            .catch((err) => {
              console.warn('Backend createProduct notice (mock fallback):', err);
            });
        }
      });

      if (newlyCreatedProducts.length > 0) {
        setProducts((prev) => [...newlyCreatedProducts, ...prev]);
      }

      // Restock already linked products & persist mapping
      const matched = lineItems.filter((it) => it.grocy_product_id);
      if (matched.length > 0) {
        matched.forEach((it) => {
          if (it.grocy_product_id) {
            handleUpsertMultiplier(merchantName, it.name, it.unit_multiplier || 1.0, it.grocy_product_id);
          }
        });

        setProducts((prev) =>
          prev.map((p) => {
            const match = matched.find((m) => m.grocy_product_id === p.id);
            if (match) {
              const multiplier = match.unit_multiplier || 1.0;
              const unitsAdded = parseFloat((match.quantity * multiplier).toFixed(2));
              const newStock = parseFloat((p.current_stock + unitsAdded).toFixed(2));
              const newRunway = p.daily_burn_rate > 0 ? parseFloat((newStock / p.daily_burn_rate).toFixed(1)) : 999;
              return { ...p, current_stock: newStock, days_runway: newRunway };
            }
            return p;
          })
        );
      }

      // Cross off shopping list
      setShoppingList((prev) =>
        prev.map((item) => {
          const matchLinked = matched.some((m) => m.grocy_product_id === item.product_id);
          const matchCreated = newlyCreatedProducts.some(
            (p) => p.name.toLowerCase() === item.item_name.toLowerCase()
          );
          if (matchLinked || matchCreated) {
            return { ...item, checked: true };
          }
          return item;
        })
      );
    }

    showNotification(`✓ Confirmed "${merchantName}" receipt! Shopping event logged & pantry restocked.`);
  };

  // Create Product in Stock with Packaging Multiplier Mapping
  const handleCreateProduct = (newProd: ProductItem, newConv: ProductUnitConversion) => {
    setProducts((prev) => [newProd, ...prev]);
    setConversions((prev) => [newConv, ...prev]);

    // Persist to backend API in background
    apiClient
      .createProduct({
        name: newProd.name,
        category: newProd.category,
        qu_stock_id: newProd.unit,
        qu_purchase_id: newProd.purchase_unit || 'pack',
        qu_factor: newConv.unit_multiplier || 1.0,
        initial_stock: newProd.current_stock || 0.0,
        daily_burn_rate: newProd.daily_burn_rate || 0.0,
        store_name: newConv.store_name,
        receipt_raw_text: newConv.receipt_raw_text,
        is_fridge_quick_tile: newProd.is_fridge_quick_tile,
      })
      .catch((err) => {
        console.warn('Backend product creation notice (offline/mock mode):', err);
      });

    showNotification(
      `📦 Created "${newProd.name}" in stock! Multiplier mapping: 1 ${newConv.purchase_unit} = ${newConv.unit_multiplier} ${newConv.stock_unit}.`
    );
  };

  // Depletion Confirmation Gate
  const handleConfirmDepletion = (id: string) => {
    setDepletions((prev) => prev.filter((d) => d.id !== id));
    showNotification('Pantry depletion confirmed and deducted from Grocy ledger.');
  };

  const handleDismissDepletion = (id: string) => {
    setDepletions((prev) => prev.filter((d) => d.id !== id));
    showNotification('Depletion proposal dismissed.');
  };

  // Shopping List Toggle
  const handleToggleShoppingItem = (id: string) => {
    setShoppingList((prev) =>
      prev.map((item) => (item.id === id ? { ...item, checked: !item.checked } : item))
    );
  };

  // Fridge Pad Quick-Deplete Action (Click to Consume)
  const handleConsumeProduct = (productId: string, amount: number) => {
    let updatedItem: ProductItem | null = null;
    setProducts((prev) =>
      prev.map((p) => {
        if (p.id === productId) {
          const newStock = Math.max(0, parseFloat((p.current_stock - amount).toFixed(2)));
          const newRunway = parseFloat((newStock / p.daily_burn_rate).toFixed(1));
          updatedItem = { ...p, current_stock: newStock, days_runway: newRunway };
          return updatedItem;
        }
        return p;
      })
    );

    if (updatedItem) {
      const item: ProductItem = updatedItem;
      const runwayMsg = item.days_runway < 7 ? `⚠️ Runway low: ${item.days_runway}d (queued to shopping)` : `${item.days_runway}d left`;
      showNotification(`📱 Fridge Pad: Consumed -${amount} ${item.unit} of ${item.name}! Remaining: ${item.current_stock} ${item.unit} (${runwayMsg})`);
    }
  };

  if (!authChecked) {
    return (
      <MantineProvider defaultColorScheme="light">
        <Box style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Text size="sm" c="dimmed">Connecting to LiftAssistant...</Text>
        </Box>
      </MantineProvider>
    );
  }

  if (!authenticated) {
    return (
      <MantineProvider defaultColorScheme="light">
        <DeviceLockScreen
          onEnrolled={(name) => {
            setAuthenticated(true);
            setCurrentDeviceName(name);
            showNotification(`Device Authorized: ${name}!`);
          }}
        />
      </MantineProvider>
    );
  }

  return (
    <MantineProvider defaultColorScheme="light">
      <AppShell
        header={{ height: 'calc(56px + env(safe-area-inset-top, 0px))' }}
        footer={{ height: 'calc(64px + env(safe-area-inset-bottom, 0px))' }}
        padding="md"
        style={{ background: '#f8f9fa', minHeight: '100vh' }}
      >
        {/* App Header (Single-Line Mobile Responsive with Safe-Area Inset) */}
        <AppShell.Header
          px="xs"
          style={{
            background: '#ffffff',
            borderBottom: '1px solid #e9ecef',
            paddingTop: 'env(safe-area-inset-top, 0px)',
            height: 'calc(56px + env(safe-area-inset-top, 0px))',
            boxSizing: 'border-box',
          }}
        >
          <Container size="sm" h="100%" px={0}>
            <Group justify="space-between" align="center" h="100%" wrap="nowrap">
              <Group gap={8} wrap="nowrap" align="center">
                <Box
                  style={{
                    background: '#228be6',
                    color: 'white',
                    borderRadius: '8px',
                    width: '30px',
                    height: '30px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 800,
                    fontSize: '15px',
                    flexShrink: 0,
                  }}
                >
                  L
                </Box>
                <Box>
                  <Text fw={800} size="sm" style={{ letterSpacing: -0.4, lineHeight: 1.2 }}>
                    LiftAssistant 3.0
                  </Text>
                  <Text size="10px" c="dimmed" visibleFrom="xs">
                    Personal Life OS
                  </Text>
                </Box>
              </Group>

              <Group gap={8} wrap="nowrap" align="center">
                <Indicator
                  color="red"
                  size={14}
                  label={unresolvedCount}
                  disabled={unresolvedCount === 0}
                  offset={2}
                >
                  <ActionIcon
                    variant={activeTab === 'notifications' ? 'filled' : 'light'}
                    color={activeTab === 'notifications' ? 'red' : 'gray'}
                    size="md"
                    radius="xl"
                    onClick={() => setActiveTab('notifications')}
                    aria-label="View notifications and action items"
                  >
                    <IconBell size={18} />
                  </ActionIcon>
                </Indicator>
                <Badge
                  color="blue"
                  size="sm"
                  variant="light"
                  style={{ cursor: 'pointer' }}
                  onClick={() => setDevicesModalOpened(true)}
                  title="Manage authorized family devices & magic links"
                >
                  📱 {currentDeviceName || 'Family Device'}
                </Badge>
              </Group>
            </Group>
          </Container>
        </AppShell.Header>

        {/* Main Content Area */}
        <AppShell.Main style={{ paddingBottom: 'calc(84px + env(safe-area-inset-bottom, 0px))' }}>
          <Container size="sm" p="xs">
            {/* Transient Action Notification */}
            {notification && (
              <Box mb="sm">
                <Notification
                  icon={<IconCheck size={18} />}
                  color="teal"
                  title="Action Logged"
                  onClose={() => setNotification(null)}
                >
                  {notification}
                </Notification>
              </Box>
            )}

            {activeTab === 'today' && (
              <TodayOverview
                templates={MOCK_TEMPLATES}
                events={events}
                onSaveQuickEvent={handleSaveQuickEvent}
                onSnapReceipt={handleSnapReceipt}
                onNavigateTab={setActiveTab}
                onSelectEvent={setSelectedEventForModal}
                onToggleComplete={handleToggleComplete}
              />
            )}

            {activeTab === 'notifications' && (
              <NotificationsView
                conflicts={conflicts}
                depletions={depletions}
                jobs={jobs}
                onResolveConflict={handleResolveConflict}
                onRescheduleConflict={handleRescheduleConflict}
                onConfirmDepletion={handleConfirmDepletion}
                onDismissDepletion={handleDismissDepletion}
                onRecheckConflicts={handleRecheckConflicts}
                isRecheckingConflicts={isRecheckingConflicts}
              />
            )}

            {activeTab === 'events' && (
              <EventsView
                events={events}
                onAddEvent={handleAddEvent}
                generators={generators}
                onAddGenerator={handleAddGenerator}
                onRunGenerator={handleRunGenerator}
                places={places}
                placesLoading={placesLoading}
                onRefreshPlaces={refreshPlaces}
                onSelectEvent={setSelectedEventForModal}
                onToggleComplete={handleToggleComplete}
              />
            )}

            {activeTab === 'pantry' && (
              <PantryView
                products={products}
                shoppingList={shoppingList}
                conversions={conversions}
                multipliers={multipliers}
                onToggleShoppingItem={handleToggleShoppingItem}
                onConsumeProduct={handleConsumeProduct}
                onCreateProduct={handleCreateProduct}
                onUpsertMultiplier={handleUpsertMultiplier}
              />
            )}

            {activeTab === 'receipts' && (
              <ReceiptsView
                jobs={jobs}
                products={products}
                multipliers={multipliers}
                onUploadReceipt={(name, type) => handleSnapReceipt('SHOPPING', undefined, name, type)}
                onConfirmJob={handleConfirmReceiptJob}
                onCreateProduct={handleCreateProduct}
                onUpsertMultiplier={handleUpsertMultiplier}
              />
            )}

            {activeTab === 'trips' && <TripsView trips={MOCK_TRIPS} />}
          </Container>
        </AppShell.Main>

        {/* Thumb-Friendly Bottom Navigation Bar (Mobile Tab Bar with Safe-Area Inset) */}
        <AppShell.Footer
          px={4}
          style={{
            background: '#ffffff',
            borderTop: '1px solid #e9ecef',
            paddingBottom: 'env(safe-area-inset-bottom, 0px)',
            height: 'calc(64px + env(safe-area-inset-bottom, 0px))',
            boxSizing: 'border-box',
          }}
        >
          <Container size="sm" h="100%">
            <Group justify="space-around" align="center" h="100%" gap={0}>
              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('today')}
              >
                <ActionIcon
                  variant={activeTab === 'today' ? 'filled' : 'subtle'}
                  color="blue"
                  size="md"
                  radius="xl"
                  mx="auto"
                >
                  <IconSun size={18} />
                </ActionIcon>
                <Text size="10px" fw={activeTab === 'today' ? 700 : 500} c={activeTab === 'today' ? 'blue' : 'dimmed'}>
                  Today
                </Text>
              </Box>

              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('notifications')}
              >
                <Indicator
                  color="red"
                  size={14}
                  label={unresolvedCount}
                  disabled={unresolvedCount === 0}
                  offset={2}
                >
                  <ActionIcon
                    variant={activeTab === 'notifications' ? 'filled' : 'subtle'}
                    color={activeTab === 'notifications' ? 'red' : 'gray'}
                    size="md"
                    radius="xl"
                    mx="auto"
                  >
                    <IconBell size={18} />
                  </ActionIcon>
                </Indicator>
                <Text
                  size="10px"
                  fw={activeTab === 'notifications' ? 700 : 500}
                  c={activeTab === 'notifications' ? 'red' : (unresolvedCount > 0 ? 'red.7' : 'dimmed')}
                >
                  Alerts
                </Text>
              </Box>

              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('events')}
              >
                <ActionIcon
                  variant={activeTab === 'events' ? 'filled' : 'subtle'}
                  color="blue"
                  size="md"
                  radius="xl"
                  mx="auto"
                >
                  <IconCalendar size={18} />
                </ActionIcon>
                <Text size="10px" fw={activeTab === 'events' ? 700 : 500} c={activeTab === 'events' ? 'blue' : 'dimmed'}>
                  Events
                </Text>
              </Box>

              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('pantry')}
              >
                <ActionIcon
                  variant={activeTab === 'pantry' ? 'filled' : 'subtle'}
                  color="blue"
                  size="md"
                  radius="xl"
                  mx="auto"
                >
                  <IconShoppingCart size={18} />
                </ActionIcon>
                <Text size="10px" fw={activeTab === 'pantry' ? 700 : 500} c={activeTab === 'pantry' ? 'blue' : 'dimmed'}>
                  Pantry
                </Text>
              </Box>

              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('receipts')}
              >
                <ActionIcon
                  variant={activeTab === 'receipts' ? 'filled' : 'subtle'}
                  color="blue"
                  size="md"
                  radius="xl"
                  mx="auto"
                >
                  <IconReceipt size={18} />
                </ActionIcon>
                <Text size="10px" fw={activeTab === 'receipts' ? 700 : 500} c={activeTab === 'receipts' ? 'blue' : 'dimmed'}>
                  Receipts
                </Text>
              </Box>

              <Box
                style={{ textAlign: 'center', cursor: 'pointer', flex: 1 }}
                onClick={() => setActiveTab('trips')}
              >
                <ActionIcon
                  variant={activeTab === 'trips' ? 'filled' : 'subtle'}
                  color="blue"
                  size="md"
                  radius="xl"
                  mx="auto"
                >
                  <IconPlane size={18} />
                </ActionIcon>
                <Text size="10px" fw={activeTab === 'trips' ? 700 : 500} c={activeTab === 'trips' ? 'blue' : 'dimmed'}>
                  Trips
                </Text>
              </Box>
            </Group>
          </Container>
        </AppShell.Footer>
      </AppShell>

      {/* Global Unified Event Modal */}
      <EventModal
        opened={!!selectedEventForModal}
        event={selectedEventForModal}
        products={products}
        multipliers={multipliers}
        onClose={() => setSelectedEventForModal(null)}
        onSaveEvent={handleSaveEvent}
        onUpsertMultiplier={handleUpsertMultiplier}
      />

      {/* Authorized Family Devices Modal */}
      <FamilyDevicesModal
        opened={devicesModalOpened}
        onClose={() => setDevicesModalOpened(false)}
        currentDeviceName={currentDeviceName}
      />
    </MantineProvider>
  );
}
