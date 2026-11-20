import React, { useEffect, useMemo, useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Tabs,
  Modal,
  TextInput,
  Textarea,
  Select,
  Chip,
  Paper,
  Box,
  Divider,
  Rating,
  SegmentedControl,
  ActionIcon,
  Tooltip,
  Loader,
  Alert,
  Table,
  Switch,
  Collapse,
  ScrollArea,
} from '@mantine/core';
import {
  IconPlus,
  IconCalendar,
  IconClock,
  IconMapPin,
  IconUser,
  IconAlertCircle,
  IconRepeat,
  IconRocket,
  IconHourglassEmpty,
  IconSortAscending,
  IconSearch,
  IconRefresh,
  IconCheck,
  IconExternalLink,
  IconTrash,
  IconRotateClockwise,
  IconAlertTriangle,
  IconMan,
  IconWoman,
  IconMoodKid,
  IconUsers,
  IconMail,
  IconRobot,
  IconSparkles,
  IconEdit,
  IconX,
  IconHistory,
  IconBulb,
  IconSettings,
  IconInfoCircle,
} from '@tabler/icons-react';
import { apiClient, ConflictCheckResult } from '../api/client';
import {
  EmailWorkerStatus,
  EventGeneratorItem,
  EventItem,
  EventType,
  GeneratorFeedbackItem,
  GeneratorRunItem,
  LearnedPromptRuleItem,
  PlaceItem,
} from '../types';
import { EventCard } from './EventCard';

interface Props {
  events: EventItem[];
  onAddEvent: (event: EventItem) => Promise<void> | void;
  generators?: EventGeneratorItem[];
  onAddGenerator?: (gen: EventGeneratorItem) => Promise<void> | void;
  onRunGenerator?: (genId: string) => Promise<void> | void;
  places?: PlaceItem[];
  placesLoading?: boolean;
  onRefreshPlaces?: () => Promise<void> | void;
  onSelectEvent?: (event: EventItem) => void;
  onToggleComplete?: (eventId: string) => void;
}

const MONTH_OPTIONS = [
  { value: '1', label: 'January' },
  { value: '2', label: 'February' },
  { value: '3', label: 'March' },
  { value: '4', label: 'April' },
  { value: '5', label: 'May' },
  { value: '6', label: 'June' },
  { value: '7', label: 'July' },
  { value: '8', label: 'August' },
  { value: '9', label: 'September' },
  { value: '10', label: 'October' },
  { value: '11', label: 'November' },
  { value: '12', label: 'December' },
];

const getMaxDaysInMonth = (monthStr: string) => {
  const m = parseInt(monthStr, 10);
  if (m === 2) return 29; // Allows leap years
  if ([4, 6, 9, 11].includes(m)) return 30;
  return 31;
};

const WEEKDAY_OPTIONS = [
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
  { value: '0', label: 'Sunday' },
];

const formatDatetimeLocal = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

const getDefaultFutureDatetime = () => {
  const d = new Date(Date.now() + 2 * 3600000); // 2 hours in the future
  d.setMinutes(0, 0, 0);
  return formatDatetimeLocal(d);
};

export const EventsView: React.FC<Props> = ({
  events,
  onAddEvent,
  generators = [],
  onAddGenerator,
  onRunGenerator,
  places: placesProp,
  placesLoading = false,
  onRefreshPlaces,
  onSelectEvent,
  onToggleComplete,
}) => {
  // Unified Event / Generator Modal State
  const [modalOpened, setModalOpened] = useState(false);
  const [isRecurring, setIsRecurring] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string | null>('upcoming');
  const [filterType, setFilterType] = useState<string>('ALL');
  const [sortBy, setSortBy] = useState<'deadline' | 'scheduled'>('deadline');

  // Common Form State
  const [title, setTitle] = useState('');
  const [eventType, setEventType] = useState<EventType>('CUSTOM');
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  const [selectedPeople, setSelectedPeople] = useState<string[]>(['Marcus', 'Mom']);
  const [description, setDescription] = useState('');

  // Verified Places & Option 2 Map Search Modal State
  const [internalPlaces, setInternalPlaces] = useState<PlaceItem[]>(placesProp ?? []);
  const [isRefreshingPlaces, setIsRefreshingPlaces] = useState(false);
  const [mapModalOpened, setMapModalOpened] = useState(false);
  const [mapQuery, setMapQuery] = useState('');
  const [mapResults, setMapResults] = useState<PlaceItem[]>([]);
  const [searchingMap, setSearchingMap] = useState(false);
  const [mapSearchError, setMapSearchError] = useState<string | null>(null);
  const [creatingPlaceKey, setCreatingPlaceKey] = useState<string | null>(null);

  // Email AI Perception Generator State
  const [generatorSubTab, setGeneratorSubTab] = useState<'email' | 'recurring'>('email');
  const [emailRuns, setEmailRuns] = useState<GeneratorRunItem[]>([]);
  const [emailFeedbacks, setEmailFeedbacks] = useState<GeneratorFeedbackItem[]>([]);
  const [promptRules, setPromptRules] = useState<LearnedPromptRuleItem[]>([]);
  const [workerStatus, setWorkerStatus] = useState<EmailWorkerStatus | null>(null);
  const [isLoadingEmailData, setIsLoadingEmailData] = useState(false);
  const [isSyncingEmail, setIsSyncingEmail] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  // Review & Feedback Modals
  const [removeModalOpened, setRemoveModalOpened] = useState(false);
  const [selectedFeedbackForRemove, setSelectedFeedbackForRemove] = useState<GeneratorFeedbackItem | null>(null);
  const [removeReason, setRemoveReason] = useState('');
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

  const [modifyModalOpened, setModifyModalOpened] = useState(false);
  const [selectedFeedbackForModify, setSelectedFeedbackForModify] = useState<GeneratorFeedbackItem | null>(null);
  const [modifyTitle, setModifyTitle] = useState('');
  const [modifyDate, setModifyDate] = useState('');
  const [modifyAmount, setModifyAmount] = useState<number>(0);
  const [modifyReason, setModifyReason] = useState('');

  const [promptModalOpened, setPromptModalOpened] = useState(false);
  const [effectivePromptData, setEffectivePromptData] = useState<any | null>(null);
  const [showRunsCollapse, setShowRunsCollapse] = useState(false);
  const [showRulesCollapse, setShowRulesCollapse] = useState(false);
  const [newRuleModalOpened, setNewRuleModalOpened] = useState(false);
  const [newRuleFeedback, setNewRuleFeedback] = useState('');
  const [newRuleInstruction, setNewRuleInstruction] = useState('');

  // Worker Run Results Modal State
  const [selectedRunForDetails, setSelectedRunForDetails] = useState<GeneratorRunItem | null>(null);
  const [runResultData, setRunResultData] = useState<{
    run: GeneratorRunItem;
    summary_message: string;
    events: GeneratorFeedbackItem[];
  } | null>(null);
  const [runResultModalOpened, setRunResultModalOpened] = useState(false);
  const [isLoadingRunResult, setIsLoadingRunResult] = useState(false);
  const [workerTypeFilter, setWorkerTypeFilter] = useState<string>('ALL');

  const loadEmailGeneratorData = async () => {
    setIsLoadingEmailData(true);
    try {
      const [statusRes, runsRes, feedbacksRes, rulesRes] = await Promise.all([
        apiClient.getEmailWorkerStatus().catch(() => null),
        apiClient.listAllGeneratorRuns().catch(() => []),
        apiClient.listGeneratedEmailEvents().catch(() => []),
        apiClient.listLearnedPromptRules().catch(() => []),
      ]);
      if (statusRes) setWorkerStatus(statusRes);
      setEmailRuns(runsRes);
      setEmailFeedbacks(feedbacksRes);
      setPromptRules(rulesRes);
    } catch (err) {
      console.warn('Failed to load email generator data:', err);
    } finally {
      setIsLoadingEmailData(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'generators') {
      void loadEmailGeneratorData();
    }
  }, [activeTab]);

  const handleViewRunResult = async (run: GeneratorRunItem) => {
    setSelectedRunForDetails(run);
    setIsLoadingRunResult(true);
    setRunResultModalOpened(true);
    try {
      const data = await apiClient.getGeneratorRunResult(run.id);
      setRunResultData(data);
    } catch (err) {
      console.error('Failed to load run details:', err);
    } finally {
      setIsLoadingRunResult(false);
    }
  };

  const handleRunDepletionWorker = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const res = await apiClient.triggerDepletionWorkerRun();
      setSyncMessage(res.summary_message);
      await loadEmailGeneratorData();
      await handleViewRunResult(res.run);
    } catch (err: any) {
      setSyncMessage(`Depletion check failed: ${err?.message || err}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleRunFacilityWorker = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const res = await apiClient.triggerFacilityWorkerRun();
      setSyncMessage(res.summary_message);
      await loadEmailGeneratorData();
      await handleViewRunResult(res.run);
    } catch (err: any) {
      setSyncMessage(`Facility check failed: ${err?.message || err}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleRunCalendarWorker = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const res = await apiClient.triggerCalendarRuleWorkerRun();
      setSyncMessage(res.summary_message);
      await loadEmailGeneratorData();
      await handleViewRunResult(res.run);
    } catch (err: any) {
      setSyncMessage(`Calendar rules evaluation failed: ${err?.message || err}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleRunMasterAll = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const res = await apiClient.triggerMasterDailyRun();
      if (res.success) {
        setSyncMessage(`Master daily run completed successfully across all 4 workers!`);
      } else {
        setSyncMessage(`Master daily run finished with issues in: ${res.failed_stages.join(', ')}`);
      }
      await loadEmailGeneratorData();
    } catch (err: any) {
      setSyncMessage(`Master run failed: ${err?.message || err}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleRetryFailed = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const res = await apiClient.triggerMasterRetryFailed();
      setSyncMessage(res.message);
      await loadEmailGeneratorData();
    } catch (err: any) {
      setSyncMessage(`Retry failed: ${err?.message || err}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleRetrySingleWorker = async (r: GeneratorRunItem) => {
    if (r.generator_type === 'CALENDAR_RULE_WORKER' || r.generator_type === 'CALENDAR_RULE_GENERATOR') {
      await handleRunCalendarWorker();
    } else if (r.generator_type === 'EMAIL_EVENT_WORKER' || r.generator_type === 'EMAIL_EVENT_GENERATOR') {
      await handleSyncNow();
    } else if (r.generator_type === 'FACILITY_CLOSURE_WORKER' || r.generator_type === 'FACILITY_WORKER') {
      await handleRunFacilityWorker();
    } else if (r.generator_type === 'INVENTORY_DEPLETION_WORKER' || r.generator_type === 'DEPLETION_WORKER') {
      await handleRunDepletionWorker();
    }
  };

  const handleSyncNow = async () => {
    setIsSyncingEmail(true);
    setSyncMessage(null);
    try {
      const run = await apiClient.triggerEmailGeneratorRun();
      setSyncMessage(`Sync completed! Scanned ${run.scanned_count} emails, created ${run.created_count} events.`);
      await loadEmailGeneratorData();
    } catch (err: any) {
      setSyncMessage(`Sync failed: ${err?.message || 'Check Gmail authentication or Ollama connection'}`);
    } finally {
      setIsSyncingEmail(false);
    }
  };

  const handleAcceptFeedback = async (item: GeneratorFeedbackItem) => {
    if (!item.event_id) return;
    try {
      await apiClient.submitEmailEventFeedback({
        event_id: item.event_id,
        status: 'ACCEPTED',
      });
      await loadEmailGeneratorData();
    } catch (err) {
      console.error('Failed to accept generated event:', err);
    }
  };

  const handleOpenRemoveModal = (item: GeneratorFeedbackItem) => {
    setSelectedFeedbackForRemove(item);
    setRemoveReason('');
    setRemoveModalOpened(true);
  };

  const handleConfirmRemove = async () => {
    if (!selectedFeedbackForRemove?.event_id) return;
    setIsSubmittingFeedback(true);
    try {
      await apiClient.submitEmailEventFeedback({
        event_id: selectedFeedbackForRemove.event_id,
        status: 'REMOVED',
        user_correction_reason: removeReason.trim() || 'User marked event as incorrect.',
      });
      setRemoveModalOpened(false);
      setSelectedFeedbackForRemove(null);
      await loadEmailGeneratorData();
    } catch (err: any) {
      alert(`Failed to remove event: ${err?.message || err}`);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  const handleOpenModifyModal = (item: GeneratorFeedbackItem) => {
    setSelectedFeedbackForModify(item);
    setModifyTitle(item.event_title || '');
    setModifyDate(item.scheduled_at ? item.scheduled_at.substring(0, 16) : '');
    setModifyAmount(item.total_amount || 0);
    setModifyReason('');
    setModifyModalOpened(true);
  };

  const handleConfirmModify = async () => {
    if (!selectedFeedbackForModify?.event_id) return;
    setIsSubmittingFeedback(true);
    try {
      await apiClient.submitEmailEventFeedback({
        event_id: selectedFeedbackForModify.event_id,
        status: 'MODIFIED',
        modified_title: modifyTitle,
        modified_scheduled_at: modifyDate ? new Date(modifyDate).toISOString() : undefined,
        modified_amount: Number(modifyAmount),
        user_correction_reason: modifyReason.trim() || undefined,
      });
      setModifyModalOpened(false);
      setSelectedFeedbackForModify(null);
      await loadEmailGeneratorData();
    } catch (err: any) {
      alert(`Failed to modify event: ${err?.message || err}`);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  const handleToggleRule = async (ruleId: string, currentActive: boolean) => {
    try {
      await apiClient.toggleLearnedPromptRule(ruleId, !currentActive);
      await loadEmailGeneratorData();
    } catch (err) {
      console.error('Failed to toggle prompt rule:', err);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    try {
      await apiClient.deleteLearnedPromptRule(ruleId);
      await loadEmailGeneratorData();
    } catch (err) {
      console.error('Failed to delete prompt rule:', err);
    }
  };

  const handleCreateRule = async () => {
    if (!newRuleFeedback.trim() || !newRuleInstruction.trim()) return;
    try {
      await apiClient.createLearnedPromptRule({
        user_feedback: newRuleFeedback.trim(),
        prompt_instruction: newRuleInstruction.trim(),
        rule_type: 'NEGATIVE',
      });
      setNewRuleModalOpened(false);
      setNewRuleFeedback('');
      setNewRuleInstruction('');
      await loadEmailGeneratorData();
    } catch (err) {
      console.error('Failed to create prompt rule:', err);
    }
  };

  const handleViewFullPrompt = async () => {
    try {
      const data = await apiClient.getEffectiveEmailPrompt();
      setEffectivePromptData(data);
      setPromptModalOpened(true);
    } catch (err) {
      console.error('Failed to load effective prompt:', err);
    }
  };


  useEffect(() => {
    if (placesProp) {
      setInternalPlaces(placesProp);
    }
  }, [placesProp]);

  const availablePlaces = placesProp ?? internalPlaces;

  const repullPlaces = async () => {
    setIsRefreshingPlaces(true);
    try {
      if (onRefreshPlaces) {
        await onRefreshPlaces();
      } else {
        const freshList = await apiClient.listPlaces();
        setInternalPlaces(freshList);
      }
    } catch (err) {
      console.warn('Failed to refresh verified places:', err);
    } finally {
      setIsRefreshingPlaces(false);
    }
  };

  useEffect(() => {
    if (!placesProp && internalPlaces.length === 0) {
      void repullPlaces();
    }
  }, []);

  const placeSelectOptions = useMemo(
    () =>
      availablePlaces.map((p) => ({
        value: p.id,
        label: p.address ? `${p.name} — ${p.address}` : p.name,
      })),
    [availablePlaces]
  );

  const selectedPlace = useMemo(
    () => availablePlaces.find((p) => p.id === selectedPlaceId) || null,
    [availablePlaces, selectedPlaceId]
  );

  const handleOpenEventModal = (recurring: boolean) => {
    setIsRecurring(recurring);
    setSaveError(null);
    setModalOpened(true);
    void repullPlaces();
  };

  const handleSearchMap = async () => {
    const q = mapQuery.trim();
    if (q.length < 2) {
      setMapSearchError('Please enter at least 2 characters (e.g., store name, city, or street address).');
      return;
    }
    setSearchingMap(true);
    setMapSearchError(null);
    try {
      const results = await apiClient.searchPlaces(q);
      setMapResults(results);
      if (results.length === 0) {
        setMapSearchError('No matching physical places found. Try including city and state (e.g. "Target Cranberry Twp PA").');
      }
    } catch (err: any) {
      setMapSearchError(err?.message || 'Failed to search physical map places.');
    } finally {
      setSearchingMap(false);
    }
  };

  const handleSelectMapCandidate = async (candidate: PlaceItem, candidateKey: string) => {
    // If candidate already matches a saved verified place, reuse it directly
    const existing = availablePlaces.find(
      (p) =>
        p.id === candidate.id ||
        (candidate.address &&
          p.address &&
          p.address.trim().toLowerCase() === candidate.address.trim().toLowerCase())
    );
    if (existing) {
      setSelectedPlaceId(existing.id);
      setMapModalOpened(false);
      return;
    }

    setCreatingPlaceKey(candidateKey);
    setMapSearchError(null);
    try {
      const created = await apiClient.createPlace({
        name: candidate.name,
        address: candidate.address || candidate.name,
        category: candidate.category || 'venue',
        latitude: candidate.latitude,
        longitude: candidate.longitude,
        map_url: candidate.map_url,
        google_place_id: candidate.google_place_id,
        notes: candidate.notes,
      });
      // Repull the authoritative list of places from the backend for <Select>
      await repullPlaces();
      setSelectedPlaceId(created.id);
      setMapModalOpened(false);
      setMapQuery('');
      setMapResults([]);
    } catch (err: any) {
      setMapSearchError(err?.message || 'Could not save verified physical place.');
    } finally {
      setCreatingPlaceKey(null);
    }
  };

  // One-Time Event State
  const [startDate, setStartDate] = useState(getDefaultFutureDatetime());
  const [deadline, setDeadline] = useState('');

  // Pre-flight conflict check state (Non-blocking)
  const [conflictWarning, setConflictWarning] = useState<ConflictCheckResult | null>(null);
  const [checkingConflict, setCheckingConflict] = useState(false);

  useEffect(() => {
    if (!modalOpened || isRecurring || !startDate) {
      setConflictWarning(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const parsedDate = new Date(startDate);
        if (isNaN(parsedDate.getTime())) {
          setCheckingConflict(false);
          return;
        }
        setCheckingConflict(true);
        const res = await apiClient.checkConflict({
          scheduled_at: parsedDate.toISOString(),
          duration_minutes: durationMinutes,
          title: title.trim() || 'Proposed Event',
          people_involved: selectedPeople,
          place_id: selectedPlaceId || undefined,
          notes: description || undefined,
        });
        setConflictWarning(res);
      } catch (err) {
        console.warn('Pre-flight conflict check failed:', err);
      } finally {
        setCheckingConflict(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [modalOpened, isRecurring, startDate, durationMinutes, selectedPeople, selectedPlaceId, title, description]);

  // Recurring Generator State
  const [recurrenceRule, setRecurrenceRule] = useState<'YEARLY' | 'MONTHLY' | 'BI_WEEKLY' | 'WEEKLY'>('YEARLY');
  const [targetMonth, setTargetMonth] = useState('11');
  const [targetDay, setTargetDay] = useState('15');
  const [targetWeekday, setTargetWeekday] = useState('1'); // 1 = Monday
  const [startTime, setStartTime] = useState('09:00');
  const [leadTimeDays, setLeadTimeDays] = useState('30');
  const [deadlineOffsetDays, setDeadlineOffsetDays] = useState('0');

  // Day Validation for Recurring Generator
  const isDateRule = recurrenceRule === 'YEARLY' || recurrenceRule === 'MONTHLY';
  const maxGenDays = recurrenceRule === 'YEARLY' ? getMaxDaysInMonth(targetMonth) : 31;
  const genDayNum = parseInt(targetDay, 10);
  const isGenDayInvalid = isRecurring && isDateRule && (!targetDay || isNaN(genDayNum) || genDayNum < 1 || genDayNum > maxGenDays);
  const genMonthLabel = MONTH_OPTIONS.find((m) => m.value === targetMonth)?.label || targetMonth;
  const genDayError = isGenDayInvalid
    ? `Day must be between 1 and ${maxGenDays} for ${recurrenceRule === 'YEARLY' ? genMonthLabel : 'selected cycle'}`
    : undefined;

  const computeEndTimeDisplay = (startIsoOrLocal: string, durationMins: number) => {
    try {
      const start = new Date(startIsoOrLocal);
      if (isNaN(start.getTime())) return '';
      const end = new Date(start.getTime() + durationMins * 60000);
      return end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  };

  const getDeadlineBadge = (deadlineStr?: string) => {
    if (!deadlineStr) return null;
    const dlDate = new Date(deadlineStr);
    // Baseline date for demo/live relative calculation
    const now = new Date('2026-11-10T00:00:00');
    const diffMs = dlDate.getTime() - now.getTime();
    const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
      return (
        <Badge color="red" variant="filled" size="xs">
          ⚠️ Overdue ({Math.abs(diffDays)}d)
        </Badge>
      );
    } else if (diffDays === 0) {
      return (
        <Badge color="orange" variant="filled" size="xs">
          🔥 Due Today
        </Badge>
      );
    } else if (diffDays <= 3) {
      return (
        <Badge color="yellow" variant="filled" size="xs" c="dark.9">
          ⏳ {diffDays}d left
        </Badge>
      );
    } else if (diffDays <= 7) {
      return (
        <Badge color="teal" variant="light" size="xs">
          📅 {diffDays}d left (This Week)
        </Badge>
      );
    } else {
      return (
        <Badge color="gray" variant="light" size="xs">
          ⏰ Deadline: {dlDate.toLocaleDateString([], { month: 'short', day: 'numeric' })}
        </Badge>
      );
    }
  };

  const handleSave = async () => {
    if (!title.trim() || isSaving) return;
    setSaveError(null);

    if (isRecurring) {
      if (isGenDayInvalid) return;

      const isDateBased = recurrenceRule === 'YEARLY' || recurrenceRule === 'MONTHLY';
      const targetW = !isDateBased ? parseInt(targetWeekday, 10) : undefined;
      const targetM = recurrenceRule === 'YEARLY' ? parseInt(targetMonth, 10) : undefined;
      const targetD = isDateBased ? (parseInt(targetDay, 10) || 1) : undefined;

      const newGen: EventGeneratorItem = {
        id: `gen_${Date.now()}`,
        name: title,
        event_type: eventType,
        recurrence_rule: recurrenceRule,
        target_month: targetM,
        target_day: targetD,
        target_weekday: targetW,
        start_time: startTime || '09:00',
        duration_minutes: durationMinutes || 60,
        lead_time_days: parseInt(leadTimeDays, 10) || (recurrenceRule === 'WEEKLY' ? 2 : 14),
        deadline_offset_days: parseInt(deadlineOffsetDays, 10) || 0,
        description,
        is_active: true,
        next_target_date: isDateBased ? `2026-${targetMonth.padStart(2, '0')}-${targetDay.padStart(2, '0')}` : undefined,
      };

      try {
        setIsSaving(true);
        if (onAddGenerator) {
          await onAddGenerator(newGen);
        }
        // Only after server responded ok then close modal and reset fields
        setModalOpened(false);
        setTitle('');
        setDeadline('');
        setDescription('');
        setSelectedPlaceId(null);
      } catch (err: any) {
        setSaveError(err?.message || 'Failed to save generator. Please try again.');
      } finally {
        setIsSaving(false);
      }
    } else {
      const start = new Date(startDate);
      // Future Event Validation: Cannot schedule events in the past
      if (isNaN(start.getTime()) || start.getTime() < Date.now() - 60000) {
        setSaveError('Scheduled events must be set in the future. Past events should be logged via Quick Actions.');
        return;
      }

      // Verified Place Validation: Must select a place
      if (!selectedPlaceId || !selectedPlace) {
        setSaveError('A verified place must be selected for future scheduled events.');
        return;
      }

      const computedEnd = !isNaN(start.getTime())
        ? new Date(start.getTime() + durationMinutes * 60000).toISOString()
        : undefined;

      const newEvent: EventItem = {
        id: `evt_custom_${Date.now()}`,
        title,
        event_type: eventType,
        scheduled_at: startDate,
        scheduled_end_at: computedEnd,
        duration_minutes: durationMinutes,
        deadline: deadline ? new Date(deadline).toISOString() : undefined,
        place_id: selectedPlace.id,
        place: selectedPlace,
        place_name: selectedPlace.name,
        place_address: selectedPlace.address,
        people_involved: selectedPeople,
        description,
        notes: description,
      };

      try {
        setIsSaving(true);
        await onAddEvent(newEvent);
        // Only after server responded ok then close modal and reset fields
        setModalOpened(false);
        setTitle('');
        setDeadline('');
        setDescription('');
        setSelectedPlaceId(null);
      } catch (err: any) {
        setSaveError(err?.message || 'Failed to save event. Please try again.');
      } finally {
        setIsSaving(false);
      }
    }
  };

  const upcomingEvents = events.filter((e) => e.scheduled_at && !e.completed_at);
  const completedEvents = events.filter((e) => e.completed_at);

  const filterEvents = (list: EventItem[]) => {
    let result = list;
    if (filterType !== 'ALL') {
      result = result.filter((e) => e.event_type === filterType);
    }

    if (sortBy === 'deadline') {
      return [...result].sort((a, b) => {
        if (a.deadline && b.deadline) {
          return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
        }
        if (a.deadline && !b.deadline) return -1;
        if (!a.deadline && b.deadline) return 1;
        const timeA = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
        const timeB = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
        return timeA - timeB;
      });
    } else {
      return [...result].sort((a, b) => {
        const timeA = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
        const timeB = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
        return timeA - timeB;
      });
    }
  };

  const getCategoryBadgeColor = (type: EventType) => {
    switch (type) {
      case 'DINING':
        return 'teal';
      case 'SHOPPING':
        return 'blue';
      case 'MAINTENANCE':
        return 'orange';
      default:
        return 'gray';
    }
  };

  return (
    <Stack gap="md">
      {/* Page Header */}
      <Card withBorder radius="md" p="md">
        <Group justify="space-between" align="center">
          <Box>
            <Text fw={800} size="lg">
              Events & Schedule Ledger
            </Text>
            <Text size="xs" c="dimmed">
              Unified schedule, recurring generators & deadline tracking
            </Text>
          </Box>
          <Group gap="xs">
            <Button
              color="indigo"
              variant="light"
              leftSection={<IconRepeat size={16} />}
              onClick={() => handleOpenEventModal(true)}
              size="xs"
            >
              + Generator
            </Button>
            <Button
              color="blue"
              leftSection={<IconPlus size={16} />}
              onClick={() => handleOpenEventModal(false)}
              size="sm"
            >
              Add Event
            </Button>
          </Group>
        </Group>

        {/* Filter Chips & Sort Controls */}
        <Group justify="space-between" mt="sm" wrap="wrap">
          <Chip.Group value={filterType} onChange={(v) => setFilterType(v as string)}>
            <Group gap="xs">
              <Chip value="ALL" size="xs">All</Chip>
              <Chip value="DINING" size="xs">Dining</Chip>
              <Chip value="SHOPPING" size="xs">Shopping</Chip>
              <Chip value="MAINTENANCE" size="xs">Maintenance</Chip>
              <Chip value="CUSTOM" size="xs">Custom</Chip>
            </Group>
          </Chip.Group>

          {activeTab === 'upcoming' && (
            <Group gap={6}>
              <Text size="11px" c="dimmed" fw={600}>
                Sort:
              </Text>
              <SegmentedControl
                size="xs"
                value={sortBy}
                onChange={(v) => setSortBy(v as 'deadline' | 'scheduled')}
                data={[
                  { label: '⏳ Deadline Urgency', value: 'deadline' },
                  { label: '📅 Scheduled Date', value: 'scheduled' },
                ]}
              />
            </Group>
          )}
        </Group>
      </Card>

      {/* Tabs: Upcoming vs Completed vs Recurring Generators */}
      <Tabs value={activeTab} onChange={setActiveTab} variant="pills" radius="xl">
        <Tabs.List mb="sm">
          <Tabs.Tab value="upcoming">
            Upcoming Schedule ({upcomingEvents.length})
          </Tabs.Tab>
          <Tabs.Tab value="completed">
            Completed Records ({completedEvents.length})
          </Tabs.Tab>
          <Tabs.Tab value="generators">
            Recurring Generators ({generators.length})
          </Tabs.Tab>
        </Tabs.List>

        {/* Tab 1: Upcoming Future Tasks */}
        <Tabs.Panel value="upcoming">
          <Stack gap="sm">
            {filterEvents(upcomingEvents).map((evt) => (
              <EventCard
                key={evt.id}
                event={evt}
                onSelectEvent={onSelectEvent}
                onToggleComplete={onToggleComplete}
              />
            ))}
          </Stack>
        </Tabs.Panel>

        {/* Tab 2: Completed Historical Records */}
        <Tabs.Panel value="completed">
          <Stack gap="sm">
            {filterEvents(completedEvents).map((evt) => (
              <EventCard
                key={evt.id}
                event={evt}
                onSelectEvent={onSelectEvent}
                onToggleComplete={onToggleComplete}
              />
            ))}
          </Stack>
        </Tabs.Panel>

        {/* Tab 3: Generators & Autonomous AI Perception */}
        <Tabs.Panel value="generators">
          <Stack gap="md">
            <SegmentedControl
              fullWidth
              size="sm"
              radius="md"
              value={generatorSubTab}
              onChange={(val) => setGeneratorSubTab(val as 'email' | 'recurring')}
              data={[
                {
                  label: (
                    <Group gap="xs" justify="center">
                      <IconMail size={16} />
                      <Text size="xs" fw={600}>Email AI Perception Generator</Text>
                      {emailFeedbacks.filter((f) => f.user_status === 'PENDING').length > 0 && (
                        <Badge size="xs" color="orange" variant="filled" circle>
                          {emailFeedbacks.filter((f) => f.user_status === 'PENDING').length}
                        </Badge>
                      )}
                    </Group>
                  ),
                  value: 'email',
                },
                {
                  label: (
                    <Group gap="xs" justify="center">
                      <IconRepeat size={16} />
                      <Text size="xs" fw={600}>Recurring Calendar Rules</Text>
                      <Badge size="xs" color="gray" variant="light">
                        {generators.length}
                      </Badge>
                    </Group>
                  ),
                  value: 'recurring',
                },
              ]}
            />

            {generatorSubTab === 'email' ? (
              <Stack gap="sm">
                {/* 1. Daily Worker Status & Controls Bar */}
                <Card withBorder radius="md" p="sm" bg="indigo.0">
                  <Group justify="space-between" align="center" wrap="wrap">
                    <Box>
                      <Group gap="xs" mb={2}>
                        <IconRobot size={18} color="#4c6ef5" />
                        <Text size="sm" fw={700} c="indigo.9">
                          Master Daily Life Worker (Background Orchestration)
                        </Text>
                        <Badge size="xs" color={(workerStatus?.is_worker_running || workerStatus?.is_running !== false) ? 'teal' : 'gray'} variant="filled">
                          {(workerStatus?.is_worker_running || workerStatus?.is_running !== false) ? 'Daily Daemon Active' : 'Daemon Standby'}
                        </Badge>
                        {workerStatus?.is_syncing && (
                          <Badge size="xs" color="blue" variant="outline">
                            Syncing In Progress...
                          </Badge>
                        )}
                      </Group>
                      <Text size="11px" c="dimmed">
                        Orchestrates recurring calendar rules, incoming email perception, facility blackout checks, and pantry depletion runway.
                      </Text>
                      {workerStatus?.last_run_time && (
                        <Text size="11px" c="indigo.8" mt={2}>
                          Last Master Run: <strong>{new Date(workerStatus.last_run_time).toLocaleString()}</strong>
                          {workerStatus.next_run_time && (
                            <> &bull; Next Scheduled: <strong>{new Date(workerStatus.next_run_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</strong></>
                          )}
                        </Text>
                      )}
                    </Box>

                    <Group gap="xs">
                      <Button
                        size="xs"
                        variant="default"
                        leftSection={<IconHistory size={14} />}
                        onClick={() => setShowRunsCollapse((v) => !v)}
                      >
                        Run History ({emailRuns.length})
                      </Button>
                      <Button
                        size="xs"
                        variant="default"
                        leftSection={<IconBulb size={14} />}
                        onClick={() => setShowRulesCollapse((v) => !v)}
                      >
                        Learned Rules ({promptRules.length})
                      </Button>
                      <Button
                        size="xs"
                        variant="outline"
                        color="indigo"
                        leftSection={<IconSparkles size={14} />}
                        onClick={handleViewFullPrompt}
                      >
                        Inspect AI Prompt
                      </Button>
                      <Button
                        size="xs"
                        color="blue"
                        loading={isSyncingEmail}
                        leftSection={<IconRefresh size={14} />}
                        onClick={handleRunMasterAll}
                      >
                        Run All Workers
                      </Button>
                    </Group>
                  </Group>

                  {syncMessage && (
                    <Alert
                      mt="xs"
                      color={syncMessage.includes('failed') ? 'red' : 'teal'}
                      withCloseButton
                      onClose={() => setSyncMessage(null)}
                      p="xs"
                    >
                      <Text size="xs">{syncMessage}</Text>
                    </Alert>
                  )}
                </Card>

                {/* 2. Run History Collapsible Section */}
                <Collapse in={showRunsCollapse}>
                  <Card withBorder radius="md" p="sm" bg="gray.0" mb="xs">
                    <Group justify="space-between" mb="xs" wrap="wrap">
                      <Group gap="xs">
                        <IconHistory size={16} />
                        <Text size="xs" fw={700}>Worker Execution Runs</Text>
                      </Group>

                      {/* Quick Trigger Buttons for Workers */}
                      <Group gap="xs" wrap="wrap">
                        <Button
                          size="compact-xs"
                          color="blue"
                          loading={isSyncingEmail}
                          leftSection={<IconRefresh size={12} />}
                          onClick={handleRunMasterAll}
                        >
                          Run All (Master)
                        </Button>
                        <Button
                          size="compact-xs"
                          color="red"
                          variant="light"
                          loading={isSyncingEmail}
                          leftSection={<IconRefresh size={12} />}
                          onClick={handleRetryFailed}
                        >
                          Retry Failed
                        </Button>
                        <Button
                          size="compact-xs"
                          color="grape"
                          loading={isSyncingEmail}
                          leftSection={<IconClock size={12} />}
                          onClick={handleRunCalendarWorker}
                        >
                          Calendar Rules
                        </Button>
                        <Button
                          size="compact-xs"
                          color="indigo"
                          loading={isSyncingEmail}
                          leftSection={<IconMail size={12} />}
                          onClick={handleSyncNow}
                        >
                          Email Sync
                        </Button>
                        <Button
                          size="compact-xs"
                          color="teal"
                          loading={isSyncingEmail}
                          leftSection={<IconRefresh size={12} />}
                          onClick={handleRunDepletionWorker}
                        >
                          Depletion Scan
                        </Button>
                        <Button
                          size="compact-xs"
                          color="orange"
                          loading={isSyncingEmail}
                          leftSection={<IconRefresh size={12} />}
                          onClick={handleRunFacilityWorker}
                        >
                          Facility Check
                        </Button>
                        <ActionIcon size="xs" variant="subtle" onClick={() => void loadEmailGeneratorData()}>
                          <IconRefresh size={12} />
                        </ActionIcon>
                      </Group>
                    </Group>

                    {/* Filter Segmented Control */}
                    <SegmentedControl
                      size="xs"
                      radius="sm"
                      value={workerTypeFilter}
                      onChange={setWorkerTypeFilter}
                      data={[
                        { label: `All (${emailRuns.length})`, value: 'ALL' },
                        { label: `Rules (${emailRuns.filter((r) => r.generator_type.includes('CALENDAR')).length})`, value: 'CALENDAR_RULE_WORKER' },
                        { label: `Email (${emailRuns.filter((r) => r.generator_type.includes('EMAIL')).length})`, value: 'EMAIL_EVENT_WORKER' },
                        { label: `Facility (${emailRuns.filter((r) => r.generator_type.includes('FACILITY')).length})`, value: 'FACILITY_CLOSURE_WORKER' },
                        { label: `Depletion (${emailRuns.filter((r) => r.generator_type.includes('DEPLETION')).length})`, value: 'INVENTORY_DEPLETION_WORKER' },
                      ]}
                      mb="xs"
                    />

                    {emailRuns.filter((r) => {
                      if (workerTypeFilter === 'ALL') return true;
                      if (workerTypeFilter === 'CALENDAR_RULE_WORKER') return r.generator_type.includes('CALENDAR');
                      if (workerTypeFilter === 'EMAIL_EVENT_WORKER') return r.generator_type.includes('EMAIL');
                      if (workerTypeFilter === 'FACILITY_CLOSURE_WORKER') return r.generator_type.includes('FACILITY');
                      if (workerTypeFilter === 'INVENTORY_DEPLETION_WORKER') return r.generator_type.includes('DEPLETION');
                      return r.generator_type === workerTypeFilter;
                    }).length === 0 ? (
                      <Text size="xs" c="dimmed" fs="italic">No execution runs logged for this worker type yet. Click one of the run buttons above to trigger a job.</Text>
                    ) : (
                      <Table striped highlightOnHover>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th>Worker</Table.Th>
                            <Table.Th>Started At</Table.Th>
                            <Table.Th>Status</Table.Th>
                            <Table.Th>Scanned</Table.Th>
                            <Table.Th>Outcome</Table.Th>
                            <Table.Th>Action</Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {emailRuns
                            .filter((r) => {
                              if (workerTypeFilter === 'ALL') return true;
                              if (workerTypeFilter === 'CALENDAR_RULE_WORKER') return r.generator_type.includes('CALENDAR');
                              if (workerTypeFilter === 'EMAIL_EVENT_WORKER') return r.generator_type.includes('EMAIL');
                              if (workerTypeFilter === 'FACILITY_CLOSURE_WORKER') return r.generator_type.includes('FACILITY');
                              if (workerTypeFilter === 'INVENTORY_DEPLETION_WORKER') return r.generator_type.includes('DEPLETION');
                              return r.generator_type === workerTypeFilter;
                            })
                            .map((r) => {
                              const isRule = r.generator_type.includes('CALENDAR');
                              const isEmail = r.generator_type.includes('EMAIL');
                              const isDepletion = r.generator_type.includes('DEPLETION');

                              const badgeColor = isRule ? 'grape' : isEmail ? 'indigo' : isDepletion ? 'teal' : 'orange';
                              const workerLabel = isRule ? 'Calendar Rules' : isEmail ? 'Email Perception' : isDepletion ? 'Pantry Depletion' : 'Facility Blackouts';

                              return (
                                <Table.Tr key={r.id}>
                                  <Table.Td>
                                    <Badge size="xs" color={badgeColor}>
                                      {workerLabel}
                                    </Badge>
                                  </Table.Td>
                                  <Table.Td>
                                    <Text size="xs">{new Date(r.started_at).toLocaleString()}</Text>
                                  </Table.Td>
                                  <Table.Td>
                                    <Badge size="xs" color={r.status === 'SUCCESS' ? 'teal' : r.status === 'FAILED' ? 'red' : 'blue'}>
                                      {r.status}
                                    </Badge>
                                  </Table.Td>
                                  <Table.Td>
                                    <Text size="xs" fw={600}>{r.scanned_count} items</Text>
                                  </Table.Td>
                                  <Table.Td>
                                    <Text size="xs" fw={600} c={r.status === 'FAILED' ? 'red' : 'teal'}>
                                      {isRule || isEmail
                                        ? `${r.created_count} events`
                                        : isDepletion
                                        ? `${r.created_count} low stock`
                                        : `${r.created_count} conflicts`}
                                    </Text>
                                  </Table.Td>
                                  <Table.Td>
                                    <Group gap="xs">
                                      <Button
                                        size="compact-xs"
                                        variant="light"
                                        color="indigo"
                                        onClick={() => handleViewRunResult(r)}
                                      >
                                        View Result
                                      </Button>
                                      {r.status === 'FAILED' && (
                                        <Button
                                          size="compact-xs"
                                          variant="filled"
                                          color="red"
                                          onClick={() => handleRetrySingleWorker(r)}
                                        >
                                          Retry
                                        </Button>
                                      )}
                                    </Group>
                                  </Table.Td>
                                </Table.Tr>
                              );
                            })}
                        </Table.Tbody>
                      </Table>
                    )}
                  </Card>
                </Collapse>


                {/* 3. Learned Prompt Rules Collapsible Section */}
                <Collapse in={showRulesCollapse}>
                  <Card withBorder radius="md" p="sm" bg="yellow.0" mb="xs">
                    <Group justify="space-between" mb="xs">
                      <Group gap="xs">
                        <IconBulb size={16} color="#d9480f" />
                        <Text size="xs" fw={700} c="orange.9">
                          Iteratively Learned Prompt Rules ({promptRules.filter((r) => r.is_active).length} Active)
                        </Text>
                      </Group>
                      <Button
                        size="compact-xs"
                        variant="light"
                        color="orange"
                        leftSection={<IconPlus size={12} />}
                        onClick={() => setNewRuleModalOpened(true)}
                      >
                        Add Custom Rule
                      </Button>
                    </Group>
                    <Text size="11px" c="dimmed" mb="xs">
                      Every time you modify an event or provide a removal reason, the system synthesizes a prompt instruction and injects it into subsequent LLM extraction calls to prevent repeating the same mistake.
                    </Text>

                    {promptRules.length === 0 ? (
                      <Text size="xs" c="dimmed" fs="italic">No learned prompt rules yet. When you remove incorrect events with reasons, learned rules will appear here.</Text>
                    ) : (
                      <Stack gap="xs">
                        {promptRules.map((r) => (
                          <Paper key={r.id} withBorder p="xs" radius="sm" bg="white">
                            <Group justify="space-between" align="flex-start">
                              <Box style={{ flex: 1 }}>
                                <Group gap="xs" mb={2}>
                                  <Badge size="xs" color={r.rule_type === 'NEGATIVE' ? 'red' : 'blue'} variant="light">
                                    {r.rule_type}
                                  </Badge>
                                  <Text size="xs" fw={600}>{r.prompt_instruction}</Text>
                                </Group>
                                <Text size="11px" c="dimmed">
                                  Feedback: &quot;{r.user_feedback}&quot; &bull; Added: {new Date(r.created_at).toLocaleDateString()}
                                </Text>
                              </Box>
                              <Group gap="xs">
                                <Switch
                                  size="xs"
                                  checked={r.is_active}
                                  onChange={() => void handleToggleRule(r.id, r.is_active)}
                                  label={r.is_active ? 'Active' : 'Off'}
                                />
                                <ActionIcon
                                  size="xs"
                                  color="red"
                                  variant="subtle"
                                  onClick={() => void handleDeleteRule(r.id)}
                                >
                                  <IconTrash size={12} />
                                </ActionIcon>
                              </Group>
                            </Group>
                          </Paper>
                        ))}
                      </Stack>
                    )}
                  </Card>
                </Collapse>

                {/* 4. Generated Events & AI Reasoning Review Section */}
                <Group justify="space-between" mt="xs" mb={4}>
                  <Text size="xs" fw={700}>
                    Extracted Events &amp; AI Perception Review ({emailFeedbacks.length})
                  </Text>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    leftSection={<IconRefresh size={12} />}
                    onClick={() => void loadEmailGeneratorData()}
                  >
                    Refresh
                  </Button>
                </Group>

                {isLoadingEmailData && emailFeedbacks.length === 0 ? (
                  <Group justify="center" p="xl">
                    <Loader size="sm" />
                    <Text size="xs" c="dimmed">Loading generated events and AI audit feedback...</Text>
                  </Group>
                ) : emailFeedbacks.length === 0 ? (
                  <Card withBorder radius="md" p="xl" style={{ textAlign: 'center' }}>
                    <IconMail size={32} color="#868e96" style={{ margin: '0 auto 8px' }} />
                    <Text size="sm" fw={600}>No Email Events Extracted Yet</Text>
                    <Text size="xs" c="dimmed" mb="md">
                      Click &quot;Sync Now&quot; above to scan recent receipts, bills, and facility schedules from Gmail.
                    </Text>
                    <Button size="xs" color="indigo" onClick={handleSyncNow} loading={isSyncingEmail}>
                      Run First Sync
                    </Button>
                  </Card>
                ) : (
                  <Stack gap="xs">
                    {emailFeedbacks.map((item) => (
                      <Card key={item.id} withBorder radius="md" p="sm" shadow="xs">
                        <Stack gap="xs">
                          {/* Row 1: Title, Category, Amount & Status */}
                          <Group justify="space-between" align="flex-start">
                            <Box style={{ flex: 1 }}>
                              <Group gap="xs" mb={2}>
                                <Text fw={700} size="sm">
                                  {item.event_title || item.email_subject || 'Untitled Event'}
                                </Text>
                                {item.llm_category && (
                                  <Badge size="xs" color={getCategoryBadgeColor((item.llm_category as EventType) || 'CUSTOM')}>
                                    {item.llm_category}
                                  </Badge>
                                )}
                                {item.total_amount && item.total_amount > 0 ? (
                                  <Badge size="xs" color="teal" variant="light">
                                    ${item.total_amount.toFixed(2)}
                                  </Badge>
                                ) : null}
                              </Group>

                              {/* Email Source Info */}
                              <Group gap="xs" c="dimmed">
                                <IconMail size={12} />
                                <Text size="11px">
                                  <strong>{item.email_from || 'Unknown Sender'}</strong>: {item.email_subject}
                                </Text>
                                {item.email_date && (
                                  <Text size="11px">&bull; {item.email_date}</Text>
                                )}
                              </Group>
                            </Box>

                            <Badge
                              size="xs"
                              variant={item.user_status === 'ACCEPTED' ? 'filled' : item.user_status === 'REMOVED' ? 'outline' : 'light'}
                              color={
                                item.user_status === 'ACCEPTED'
                                  ? 'teal'
                                  : item.user_status === 'MODIFIED'
                                  ? 'blue'
                                  : item.user_status === 'REMOVED'
                                  ? 'red'
                                  : item.user_status === 'AUTOPAY_SKIPPED'
                                  ? 'gray'
                                  : 'orange'
                              }
                            >
                              {item.user_status === 'AUTOPAY_SKIPPED' ? 'Skipped (Auto-Pay)' : item.user_status}
                            </Badge>
                          </Group>

                          {/* Row 2: AI Reasoning Callout */}
                          <Paper withBorder p="xs" radius="sm" bg="indigo.0" style={{ borderColor: '#bac8ff' }}>
                            <Group gap="xs" align="flex-start">
                              <IconRobot size={15} color="#4c6ef5" style={{ marginTop: 2, flexShrink: 0 }} />
                              <Box style={{ flex: 1 }}>
                                <Text size="xs" fw={600} c="indigo.9">
                                  🤖 AI Extraction Reasoning:
                                </Text>
                                <Text size="11px" c="dark.7">
                                  {item.llm_reason || 'Identified event payload from email body.'}
                                </Text>
                              </Box>
                            </Group>
                          </Paper>

                          {/* User Correction Notice if present */}
                          {item.user_correction_reason && (
                            <Paper withBorder p="xs" radius="sm" bg="orange.0" style={{ borderColor: '#ffd8a8' }}>
                              <Text size="11px" c="orange.9">
                                <strong>User Correction Feedback:</strong> {item.user_correction_reason}
                              </Text>
                            </Paper>
                          )}

                          {/* Row 3: Action Controls */}
                          {item.user_status !== 'REMOVED' && item.user_status !== 'AUTOPAY_SKIPPED' && item.event_id && (
                            <Group justify="flex-end" gap="xs" mt={4}>
                              {item.user_status === 'PENDING' && (
                                <Button
                                  size="xs"
                                  color="teal"
                                  variant="light"
                                  leftSection={<IconCheck size={13} />}
                                  onClick={() => void handleAcceptFeedback(item)}
                                >
                                  Accept &amp; Keep
                                </Button>
                              )}
                              <Button
                                size="xs"
                                color="blue"
                                variant="light"
                                leftSection={<IconEdit size={13} />}
                                onClick={() => handleOpenModifyModal(item)}
                              >
                                Modify Event
                              </Button>
                              <Button
                                size="xs"
                                color="red"
                                variant="light"
                                leftSection={<IconTrash size={13} />}
                                onClick={() => handleOpenRemoveModal(item)}
                              >
                                Remove Incorrect
                              </Button>
                            </Group>
                          )}
                        </Stack>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Stack>
            ) : (
              /* Existing Tab: Recurring Calendar Generators */
              <Stack gap="sm">
                <Card withBorder radius="md" p="sm" bg="gray.0">
                  <Group justify="space-between">
                    <Box>
                      <Text size="xs" fw={700}>
                        Auto-Generating Calendar Rules
                      </Text>
                      <Text size="11px" c="dimmed">
                        Annual, monthly, and recurring events automatically spawn tasks with advance lead time and strict deadlines.
                      </Text>
                    </Box>
                    <Button
                      size="xs"
                      color="indigo"
                      leftSection={<IconPlus size={14} />}
                      onClick={() => {
                        setIsRecurring(true);
                        setModalOpened(true);
                      }}
                    >
                      New Generator
                    </Button>
                  </Group>
                </Card>

                {generators.map((gen) => (
                  <Card key={gen.id} withBorder radius="md" p="sm" shadow="xs">
                    <Group justify="space-between" align="flex-start">
                      <Box style={{ flex: 1 }}>
                        <Group gap="xs" mb={4}>
                          <Text fw={700} size="sm">
                            {gen.name}
                          </Text>
                          <Badge size="xs" color={getCategoryBadgeColor(gen.event_type)}>
                            {gen.event_type}
                          </Badge>
                          <Badge size="xs" variant="outline" color="indigo">
                            🔁 {gen.recurrence_rule}
                          </Badge>
                          {gen.is_active && (
                            <Badge size="xs" color="teal" variant="light">
                              Active
                            </Badge>
                          )}
                        </Group>

                        {gen.description && (
                          <Text size="xs" c="dark.4" mb={6}>
                            {gen.description}
                          </Text>
                        )}

                        <Group gap="md" wrap="wrap">
                          <Text size="11px" c="dimmed">
                            📅 Target:{' '}
                            <strong>
                              {gen.recurrence_rule === 'YEARLY'
                                ? `${MONTH_OPTIONS.find((m) => m.value === String(gen.target_month))?.label || `Month ${gen.target_month}`} ${gen.target_day}`
                                : gen.recurrence_rule === 'MONTHLY'
                                ? `Day ${gen.target_day} of month`
                                : gen.recurrence_rule === 'BI_WEEKLY'
                                ? `Every 2 weeks on ${WEEKDAY_OPTIONS.find((w) => w.value === String(gen.target_weekday ?? 1))?.label || 'Monday'}`
                                : `Every ${WEEKDAY_OPTIONS.find((w) => w.value === String(gen.target_weekday ?? 1))?.label || 'Monday'}`}
                            </strong>
                          </Text>
                          <Text size="11px" c="dimmed">
                            ⏰ Time:{' '}
                            <strong>
                              {gen.start_time || '09:00'} ({gen.duration_minutes || 60}m)
                            </strong>
                          </Text>
                          <Text size="11px" c="dimmed">
                            ⏳ Lead Time: <strong>{gen.lead_time_days} days ahead</strong>
                          </Text>
                          <Text size="11px" c="dimmed">
                            ⏰ Deadline: <strong>+{gen.deadline_offset_days} days offset</strong>
                          </Text>
                        </Group>
                      </Box>

                      <Button
                        size="xs"
                        color="indigo"
                        variant="light"
                        leftSection={<IconRocket size={14} />}
                        onClick={() => onRunGenerator && onRunGenerator(gen.id)}
                      >
                        Spawn Now
                      </Button>
                    </Group>
                  </Card>
                ))}
              </Stack>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>

      {/* Remove Incorrect Event Modal with Reason Prompt */}
      <Modal
        opened={removeModalOpened}
        onClose={() => setRemoveModalOpened(false)}
        title={
          <Group gap="xs">
            <IconAlertTriangle size={18} color="#e03131" />
            <Text fw={700} size="sm">Remove Incorrect Event &amp; Train AI</Text>
          </Group>
        }
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Removing &quot;<strong>{selectedFeedbackForRemove?.event_title || selectedFeedbackForRemove?.email_subject}</strong>&quot; will delete it from your ledger.
          </Text>
          <Text size="xs" fw={600}>
            Please tell us why this was incorrect so the AI learns to avoid similar mistakes:
          </Text>
          <Textarea
            rows={3}
            placeholder="e.g. This was an advertisement offering a discount, not a purchase receipt; or This is a reminder without payment due."
            value={removeReason}
            onChange={(e) => setRemoveReason(e.currentTarget.value)}
          />
          <Group justify="flex-end" mt="xs">
            <Button variant="default" size="xs" onClick={() => setRemoveModalOpened(false)}>
              Cancel
            </Button>
            <Button
              color="red"
              size="xs"
              loading={isSubmittingFeedback}
              onClick={handleConfirmRemove}
            >
              Remove Event &amp; Update AI Prompt
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Modify Event Modal */}
      <Modal
        opened={modifyModalOpened}
        onClose={() => setModifyModalOpened(false)}
        title={
          <Group gap="xs">
            <IconEdit size={18} color="#1971c2" />
            <Text fw={700} size="sm">Modify Generated Event</Text>
          </Group>
        }
      >
        <Stack gap="sm">
          <TextInput
            label="Event Title"
            value={modifyTitle}
            onChange={(e) => setModifyTitle(e.currentTarget.value)}
          />
          <TextInput
            label="Scheduled Date / Time"
            type="datetime-local"
            value={modifyDate}
            onChange={(e) => setModifyDate(e.currentTarget.value)}
          />
          <TextInput
            label="Total Amount ($)"
            type="number"
            value={modifyAmount}
            onChange={(e) => setModifyAmount(parseFloat(e.currentTarget.value) || 0)}
          />
          <Textarea
            label="Reason for Modification (Optional guidance for LLM)"
            placeholder="e.g. Due date should match statement due date, merchant name was formatted incorrectly"
            value={modifyReason}
            onChange={(e) => setModifyReason(e.currentTarget.value)}
          />
          <Group justify="flex-end" mt="xs">
            <Button variant="default" size="xs" onClick={() => setModifyModalOpened(false)}>
              Cancel
            </Button>
            <Button
              color="blue"
              size="xs"
              loading={isSubmittingFeedback}
              onClick={handleConfirmModify}
            >
              Save Changes &amp; Train AI
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Inspect AI Prompt Modal */}
      <Modal
        opened={promptModalOpened}
        onClose={() => setPromptModalOpened(false)}
        size="lg"
        title={
          <Group gap="xs">
            <IconSparkles size={18} color="#4c6ef5" />
            <Text fw={700} size="sm">Active LLM Prompt &amp; Injected Rules</Text>
          </Group>
        }
      >
        <Stack gap="xs">
          <Text size="xs" c="dimmed">
            This is the live system prompt passed to Gemma LLM for perception, showing how your corrections and feedback rules are dynamically incorporated:
          </Text>
          <Paper withBorder p="xs" radius="sm" bg="gray.1" style={{ maxHeight: '400px', overflowY: 'auto' }}>
            <pre style={{ fontSize: '11px', whiteSpace: 'pre-wrap', margin: 0 }}>
              {effectivePromptData?.effective_prompt || 'Loading prompt...'}
            </pre>
          </Paper>
          <Group justify="flex-end" mt="xs">
            <Button size="xs" variant="default" onClick={() => setPromptModalOpened(false)}>
              Close
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Add Custom Prompt Rule Modal */}
      <Modal
        opened={newRuleModalOpened}
        onClose={() => setNewRuleModalOpened(false)}
        title={
          <Group gap="xs">
            <IconBulb size={18} color="#f08c00" />
            <Text fw={700} size="sm">Teach LLM Custom Prompt Rule</Text>
          </Group>
        }
      >
        <Stack gap="sm">
          <TextInput
            label="User Feedback / Description"
            placeholder="e.g. Hulu emails with $4.99 are promos, not receipts"
            value={newRuleFeedback}
            onChange={(e) => setNewRuleFeedback(e.currentTarget.value)}
          />
          <Textarea
            label="Instruction to Inject into LLM Prompt"
            placeholder="e.g. USER CORRECTION: Streaming promotional pitches with pricing must be classified as SKIP with is_event: false."
            rows={3}
            value={newRuleInstruction}
            onChange={(e) => setNewRuleInstruction(e.currentTarget.value)}
          />
          <Group justify="flex-end" mt="xs">
            <Button variant="default" size="xs" onClick={() => setNewRuleModalOpened(false)}>
              Cancel
            </Button>
            <Button color="orange" size="xs" onClick={handleCreateRule}>
              Save Rule
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Worker Run Outcome Modal (Displays Event List for Email Worker, Summary Message for Depletion/Facility Workers) */}
      <Modal
        opened={runResultModalOpened}
        onClose={() => setRunResultModalOpened(false)}
        size="lg"
        title={
          <Group gap="xs">
            <IconInfoCircle size={18} color="#4c6ef5" />
            <Text fw={700} size="sm">
              Worker Job Outcome: {selectedRunForDetails?.generator_type.replace(/_/g, ' ')}
            </Text>
            {selectedRunForDetails && (
              <Badge
                size="xs"
                color={selectedRunForDetails.status === 'SUCCESS' ? 'teal' : selectedRunForDetails.status === 'FAILED' ? 'red' : 'blue'}
              >
                {selectedRunForDetails.status}
              </Badge>
            )}
          </Group>
        }
      >
        {isLoadingRunResult ? (
          <Group justify="center" p="xl">
            <Loader size="sm" />
            <Text size="xs" c="dimmed">Loading worker run result...</Text>
          </Group>
        ) : runResultData ? (
          <Stack gap="sm">
            {/* Summary Message Banner */}
            <Alert
              color="indigo"
              variant="light"
              icon={<IconInfoCircle size={16} />}
              title="Execution Summary"
            >
              <Text size="xs" fw={500}>{runResultData.summary_message}</Text>
              <Group gap="md" mt={4}>
                <Text size="11px" c="dimmed">
                  Started: {new Date(runResultData.run.started_at).toLocaleString()}
                </Text>
                {runResultData.run.completed_at && (
                  <Text size="11px" c="dimmed">
                    Completed: {new Date(runResultData.run.completed_at).toLocaleTimeString()}
                  </Text>
                )}
                <Text size="11px" c="dimmed">
                  Items Scanned: <strong>{runResultData.run.scanned_count}</strong> &bull; Created/Actioned: <strong>{runResultData.run.created_count}</strong>
                </Text>
              </Group>
            </Alert>

            {/* If Email Event Generator and events were produced */}
            {runResultData.events && runResultData.events.length > 0 ? (
              <Stack gap="xs">
                <Text size="xs" fw={700}>
                  Generated Life Events ({runResultData.events.length})
                </Text>
                {runResultData.events.map((evt) => (
                  <Card key={evt.id} withBorder p="xs" radius="sm">
                    <Stack gap={4}>
                      <Group justify="space-between" align="flex-start">
                        <Box style={{ flex: 1 }}>
                          <Group gap="xs" mb={2}>
                            <Text size="xs" fw={700}>{evt.event_title || evt.email_subject}</Text>
                            {evt.llm_category && (
                              <Badge size="xs" color={getCategoryBadgeColor((evt.llm_category as EventType) || 'CUSTOM')}>
                                {evt.llm_category}
                              </Badge>
                            )}
                            {evt.total_amount && evt.total_amount > 0 ? (
                              <Badge size="xs" color="teal" variant="light">
                                ${evt.total_amount.toFixed(2)}
                              </Badge>
                            ) : null}
                          </Group>
                          <Text size="11px" c="dimmed">
                            {evt.email_from}: {evt.email_subject}
                          </Text>
                        </Box>
                        <Badge
                          size="xs"
                          color={evt.user_status === 'ACCEPTED' ? 'teal' : evt.user_status === 'REMOVED' ? 'red' : 'orange'}
                        >
                          {evt.user_status}
                        </Badge>
                      </Group>

                      {/* AI Reasoning Callout */}
                      <Paper withBorder p="xs" radius="xs" bg="indigo.0" style={{ borderColor: '#dbe4ff' }}>
                        <Text size="11px" c="indigo.9">
                          🤖 <strong>AI Reasoning:</strong> {evt.llm_reason || 'Extracted by Gemma LLM'}
                        </Text>
                      </Paper>
                    </Stack>
                  </Card>
                ))}
              </Stack>
            ) : runResultData.run.generator_type === 'EMAIL_EVENT_GENERATOR' ? (
              <Paper withBorder p="md" radius="sm" bg="gray.0" style={{ textAlign: 'center' }}>
                <Text size="xs" c="dimmed">
                  This email scan did not generate any events (e.g. no new receipts or bills found in the scanned batch).
                </Text>
              </Paper>
            ) : (
              /* For Depletion Worker and Facility Worker: Clean structured summary */
              <Paper withBorder p="md" radius="sm" bg="gray.0">
                <Text size="xs" fw={600} mb={4}>
                  {runResultData.run.generator_type === 'DEPLETION_WORKER' ? '🛒 Inventory Health Breakdown' : '🏊 Facility & Conflict Status'}
                </Text>
                <Text size="xs" c="dark.6">
                  {runResultData.summary_message}
                </Text>
              </Paper>
            )}

            <Group justify="flex-end" mt="xs">
              <Button size="xs" variant="default" onClick={() => setRunResultModalOpened(false)}>
                Close
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>



      {/* Unified Modal: Life Event & Recurring Generator Builder */}
      <Modal
        opened={modalOpened}
        onClose={() => !isSaving && setModalOpened(false)}
        closeOnClickOutside={!isSaving}
        closeOnEscape={!isSaving}
        withCloseButton={!isSaving}
        title={
          <Group gap="xs">
            <Text fw={700} size="md">
              {isRecurring ? '🔁 Add Recurring Event Generator' : '➕ Add Life Event'}
            </Text>
            <Badge size="xs" color={isRecurring ? 'indigo' : 'blue'} variant="light">
              {isRecurring ? 'Recurring Rule' : 'One-Time Event'}
            </Badge>
          </Group>
        }
        radius="md"
        centered
        size="md"
      >
        <Stack gap="sm">
          {/* Mode Switcher */}
          <SegmentedControl
            fullWidth
            value={isRecurring ? 'RECURRING' : 'ONETIME'}
            onChange={(val) => setIsRecurring(val === 'RECURRING')}
            data={[
              { label: '📅 One-Time Event', value: 'ONETIME' },
              { label: '🔁 Recurring Generator', value: 'RECURRING' },
            ]}
          />

          <TextInput
            label={isRecurring ? 'Generator Name / Event Title' : 'Title / Short Summary'}
            placeholder={
              isRecurring
                ? 'e.g. Butler County Property Tax, PA State Inspection, Tax Return'
                : 'e.g. Marcus Orthodontist Checkup, Piano Recital'
            }
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
            required
          />

          <Select
            label="Event Category / Tag"
            data={[
              { value: 'CUSTOM', label: 'Custom / General' },
              { value: 'DINING', label: 'Dining' },
              { value: 'SHOPPING', label: 'Shopping' },
              { value: 'MAINTENANCE', label: 'Maintenance' },
            ]}
            value={eventType}
            onChange={(v) => setEventType((v as EventType) || 'CUSTOM')}
          />

          {/* Conditional Timing Block: One-Time vs Recurring */}
          {!isRecurring ? (
            <>
              {/* START DATETIME (Future Events Only) with Mobile Status Icon */}
              <Box>
                <Group justify="space-between" align="center" mb={2}>
                  <Text size="xs" fw={500}>Start Datetime (Future)</Text>
                  {/* Conflict Status Icon Pill with Tooltip */}
                  {checkingConflict ? (
                    <Group gap={4}>
                      <Loader size={12} color="gray" />
                      <Text size="10px" c="dimmed">Checking...</Text>
                    </Group>
                  ) : conflictWarning && conflictWarning.has_conflict ? (
                    <Tooltip label={conflictWarning.conflicts.map((c) => c.title).join(' • ') || 'Schedule conflict detected'} multiline w={220} withArrow>
                      <Badge color="red" size="xs" variant="filled" leftSection={<IconAlertTriangle size={11} />} style={{ cursor: 'pointer' }}>
                        Conflict
                      </Badge>
                    </Tooltip>
                  ) : conflictWarning && !conflictWarning.has_conflict && startDate ? (
                    <Tooltip label="Time slot & attendees clear" withArrow>
                      <Badge color="teal" size="xs" variant="light" leftSection={<IconCheck size={11} />} style={{ cursor: 'pointer' }}>
                        Clear
                      </Badge>
                    </Tooltip>
                  ) : null}
                </Group>
                <TextInput
                  type="datetime-local"
                  size="xs"
                  value={startDate}
                  min={formatDatetimeLocal(new Date())}
                  onChange={(e) => {
                    setStartDate(e.currentTarget.value);
                    setSaveError(null);
                  }}
                  error={
                    new Date(startDate).getTime() < Date.now() - 60000
                      ? 'Event time cannot be in the past'
                      : undefined
                  }
                  leftSection={<IconClock size={16} />}
                />
                {conflictWarning && conflictWarning.has_conflict && (
                  <Text size="11px" c="red.8" fw={500} mt={4} truncate>
                    ⚠️ {conflictWarning.conflicts[0]?.title || 'Conflict detected on calendar'}
                  </Text>
                )}
              </Box>

              {/* DEADLINE INPUT */}
              <TextInput
                label="Deadline (Optional)"
                description="Auto-surfaces item with urgency countdown badges"
                type="datetime-local"
                value={deadline}
                onChange={(e) => setDeadline(e.currentTarget.value)}
                leftSection={<IconHourglassEmpty size={16} />}
              />
            </>
          ) : (
            <>
              <Select
                label="Recurrence Cycle"
                data={[
                  { value: 'YEARLY', label: 'Yearly (Annual)' },
                  { value: 'MONTHLY', label: 'Monthly' },
                  { value: 'BI_WEEKLY', label: 'Every 2 Weeks (Bi-Weekly)' },
                  { value: 'WEEKLY', label: 'Weekly' },
                ]}
                value={recurrenceRule}
                onChange={(v) => {
                  const rule = (v as any) || 'YEARLY';
                  setRecurrenceRule(rule);
                  if (rule === 'WEEKLY' && parseInt(leadTimeDays, 10) > 7) {
                    setLeadTimeDays('2');
                  } else if (rule === 'BI_WEEKLY' && parseInt(leadTimeDays, 10) > 14) {
                    setLeadTimeDays('3');
                  }
                }}
              />

              {/* Day / Date Selector based on cycle */}
              {recurrenceRule === 'WEEKLY' || recurrenceRule === 'BI_WEEKLY' ? (
                <Select
                  label="Day of Week"
                  description={recurrenceRule === 'BI_WEEKLY' ? 'Repeats every two weeks on this day' : 'Repeats every week on this day'}
                  data={WEEKDAY_OPTIONS}
                  value={targetWeekday}
                  onChange={(v) => setTargetWeekday(v || '1')}
                  required
                />
              ) : (
                <Group grow align="flex-start">
                  {recurrenceRule === 'YEARLY' && (
                    <Select
                      label="Target Month"
                      data={MONTH_OPTIONS}
                      value={targetMonth}
                      onChange={(v) => {
                        const newMonth = v || '1';
                        setTargetMonth(newMonth);
                        const maxD = getMaxDaysInMonth(newMonth);
                        if (parseInt(targetDay, 10) > maxD) {
                          setTargetDay(String(maxD));
                        }
                      }}
                      required
                    />
                  )}
                  <TextInput
                    label={recurrenceRule === 'YEARLY' ? `Target Day (1-${maxGenDays})` : 'Target Day (1-31)'}
                    type="number"
                    min={1}
                    max={maxGenDays}
                    value={targetDay}
                    onChange={(e) => setTargetDay(e.currentTarget.value)}
                    error={genDayError}
                    required
                  />
                </Group>
              )}

              {/* Event Start Time */}
              <TextInput
                label="Event Start Time"
                description="Scheduled appointment start time when spawned"
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.currentTarget.value)}
                leftSection={<IconClock size={16} />}
              />

              {/* Lead Time & Deadline Offset */}
              <Group grow>
                <TextInput
                  label="Lead Time (Days Ahead)"
                  description="When to spawn event before target date"
                  type="number"
                  value={leadTimeDays}
                  onChange={(e) => setLeadTimeDays(e.currentTarget.value)}
                />
                <TextInput
                  label="Deadline Offset (Days)"
                  description="Days from target date to final deadline"
                  type="number"
                  value={deadlineOffsetDays}
                  onChange={(e) => setDeadlineOffsetDays(e.currentTarget.value)}
                />
              </Group>
            </>
          )}

          {/* DURATION / LASTING TIME (Shared) */}
          <Box>
            <Group justify="space-between" mb={6}>
              <Text size="xs" fw={500}>
                Lasting Time / Duration
              </Text>
              <Badge size="sm" variant="light" color={isRecurring ? 'indigo' : 'blue'}>
                {durationMinutes} min ({durationMinutes < 60 ? `${durationMinutes}m` : durationMinutes === 60 ? '1 hr' : `${durationMinutes / 60} hrs`})
                {!isRecurring && startDate && ` • Ends at ${computeEndTimeDisplay(startDate, durationMinutes)}`}
              </Badge>
            </Group>
            <Group gap="xs">
              {[15, 30, 45, 60, 90, 120].map((mins) => (
                <Button
                  key={mins}
                  size="xs"
                  variant={durationMinutes === mins ? 'filled' : 'default'}
                  color={durationMinutes === mins ? (isRecurring ? 'indigo' : 'blue') : undefined}
                  onClick={() => setDurationMinutes(mins)}
                >
                  {mins < 60 ? `${mins}m` : mins === 60 ? '1 hr' : `${mins / 60} hrs`}
                </Button>
              ))}
            </Group>
          </Box>

          {/* PEOPLE INVOLVED (Shared) */}
          <Box>
            <Text size="xs" fw={500} mb={4}>
              People Involved
            </Text>
            <Chip.Group
              multiple
              value={selectedPeople}
              onChange={setSelectedPeople}
            >
              <Group gap="xs">
                <Chip value="Dad" size="xs">
                  <Group gap={4} wrap="nowrap">
                    <IconMan size={12} color="#1c7ed6" />
                    <span>Dad</span>
                  </Group>
                </Chip>
                <Chip value="Mom" size="xs">
                  <Group gap={4} wrap="nowrap">
                    <IconWoman size={12} color="#e64980" />
                    <span>Mom</span>
                  </Group>
                </Chip>
                <Chip value="Marcus" size="xs">
                  <Group gap={4} wrap="nowrap">
                    <IconMoodKid size={12} color="#12b886" />
                    <span>Marcus</span>
                  </Group>
                </Chip>
              </Group>
            </Chip.Group>
          </Box>

          {/* LOCATION (Shared — Option 2: Verified Physical Places Autocomplete + Map Search) */}
          <Box>
            <Group justify="space-between" align="center" mb={4}>
              <Group gap={6}>
                <Text size="xs" fw={500}>
                  Location / Venue (Verified Place)
                </Text>
                {!isRecurring && (
                  <Badge size="xs" color="red" variant="light">
                    Required
                  </Badge>
                )}
              </Group>
              <Group gap={6}>
                <Tooltip label="Refresh verified places list">
                  <ActionIcon
                    variant="subtle"
                    size="xs"
                    color="gray"
                    onClick={() => void repullPlaces()}
                    loading={isRefreshingPlaces || placesLoading}
                    aria-label="Refresh places list"
                  >
                    <IconRefresh size={13} />
                  </ActionIcon>
                </Tooltip>
                <Button
                  size="compact-xs"
                  variant="light"
                  color="teal"
                  leftSection={<IconSearch size={12} />}
                  onClick={() => {
                    setMapSearchError(null);
                    setMapModalOpened(true);
                  }}
                  disabled={isSaving}
                >
                  Search Map / Add Place
                </Button>
              </Group>
            </Group>

            <Select
              placeholder={
                isRefreshingPlaces || placesLoading
                  ? 'Loading verified places...'
                  : 'Search or pick a verified place...'
              }
              data={placeSelectOptions}
              value={selectedPlaceId}
              onChange={(val) => {
                setSelectedPlaceId(val);
                setSaveError(null);
              }}
              searchable
              clearable
              error={!isRecurring && !selectedPlaceId && saveError?.includes('place') ? 'A verified place must be selected' : undefined}
              leftSection={<IconMapPin size={16} />}
              nothingFoundMessage="No saved place matches — click 'Search Map / Add Place' above"
              disabled={isSaving}
            />

            {selectedPlace && (
              <Paper p="xs" mt={6} radius="sm" withBorder bg="teal.0">
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <Box style={{ minWidth: 0 }}>
                    <Text size="xs" fw={700} c="teal.9" truncate>
                      📍 {selectedPlace.name}
                    </Text>
                    {selectedPlace.address && (
                      <Text size="11px" c="dark.6" lineClamp={2}>
                        {selectedPlace.address}
                      </Text>
                    )}
                  </Box>
                  {selectedPlace.map_url && (
                    <ActionIcon
                      component="a"
                      href={selectedPlace.map_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      size="xs"
                      variant="subtle"
                      color="teal"
                      title="View on Map"
                    >
                      <IconExternalLink size={13} />
                    </ActionIcon>
                  )}
                </Group>
              </Paper>
            )}
          </Box>

          {/* DESCRIPTION (Shared) */}
          <Textarea
            label="Description / Instructions"
            placeholder="Notes, instructions, details..."
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            rows={2}
          />

          {saveError && (
            <Text size="xs" c="red.7" fw={600}>
              ⚠️ {saveError}
            </Text>
          )}

          {/* MODAL ACTIONS */}
          <Group justify="flex-end" mt="md">
            <Button
              variant="default"
              onClick={() => setModalOpened(false)}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button
              color={isRecurring ? 'indigo' : 'blue'}
              onClick={handleSave}
              loading={isSaving}
              disabled={isSaving || isGenDayInvalid}
            >
              {isRecurring ? 'Save Generator' : 'Save Event'}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Option 2: Physical Map Search & Place Grounding Modal */}
      <Modal
        opened={mapModalOpened}
        onClose={() => !creatingPlaceKey && setMapModalOpened(false)}
        closeOnClickOutside={!creatingPlaceKey}
        closeOnEscape={!creatingPlaceKey}
        title={
          <Group gap="xs">
            <IconMapPin size={18} color="#0ca678" />
            <Text fw={700} size="md">
              Search Map & Ground Physical Place
            </Text>
          </Group>
        }
        radius="md"
        centered
        size="md"
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Search real-world venues or street addresses via OpenStreetMap. Selecting a result grounds its address & GPS coordinates into your saved places.
          </Text>

          <Group gap="xs" align="flex-end" wrap="nowrap">
            <TextInput
              style={{ flex: 1 }}
              label="Venue Name or Address"
              placeholder="e.g. Target Cranberry Twp PA, UPMC Wexford"
              value={mapQuery}
              onChange={(e) => setMapQuery(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleSearchMap();
                }
              }}
              leftSection={<IconSearch size={15} />}
              disabled={searchingMap || !!creatingPlaceKey}
            />
            <Button
              color="teal"
              onClick={() => void handleSearchMap()}
              loading={searchingMap}
              disabled={!!creatingPlaceKey}
            >
              Search
            </Button>
          </Group>

          {mapSearchError && (
            <Alert color="orange" variant="light" p="xs">
              <Text size="xs">{mapSearchError}</Text>
            </Alert>
          )}

          {searchingMap && (
            <Group justify="center" py="md">
              <Loader size="sm" color="teal" />
              <Text size="xs" c="dimmed">
                Searching OpenStreetMap & saved venues...
              </Text>
            </Group>
          )}

          {!searchingMap && mapResults.length > 0 && (
            <Stack gap="xs" mah={320} style={{ overflowY: 'auto' }}>
              {mapResults.map((cand, idx) => {
                const candKey = `${cand.id || 'osm'}_${idx}`;
                const alreadySaved = availablePlaces.some(
                  (p) =>
                    p.id === cand.id ||
                    (cand.address &&
                      p.address &&
                      p.address.trim().toLowerCase() === cand.address.trim().toLowerCase())
                );
                const isCreating = creatingPlaceKey === candKey;

                return (
                  <Card key={candKey} withBorder radius="sm" p="xs" shadow="xs">
                    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
                      <Box style={{ flex: 1, minWidth: 0 }}>
                        <Group gap={6} mb={2} wrap="wrap">
                          <Text size="sm" fw={700} truncate>
                            {cand.name}
                          </Text>
                          {cand.category && (
                            <Badge size="xs" color="gray" variant="light">
                              {cand.category}
                            </Badge>
                          )}
                          {alreadySaved && (
                            <Badge size="xs" color="teal" variant="light">
                              Already Saved
                            </Badge>
                          )}
                        </Group>
                        {cand.address && (
                          <Text size="xs" c="dark.4" lineClamp={2}>
                            {cand.address}
                          </Text>
                        )}
                        {cand.latitude !== undefined && cand.longitude !== undefined && (
                          <Text size="10px" c="dimmed" mt={2}>
                            GPS: {cand.latitude.toFixed(5)}, {cand.longitude.toFixed(5)}
                          </Text>
                        )}
                      </Box>

                      <Button
                        size="xs"
                        color={alreadySaved ? 'blue' : 'teal'}
                        variant={alreadySaved ? 'light' : 'filled'}
                        leftSection={<IconCheck size={13} />}
                        loading={isCreating}
                        disabled={!!creatingPlaceKey && !isCreating}
                        onClick={() => void handleSelectMapCandidate(cand, candKey)}
                        style={{ flexShrink: 0 }}
                      >
                        {alreadySaved ? 'Use Place' : 'Save & Select'}
                      </Button>
                    </Group>
                  </Card>
                );
              })}
            </Stack>
          )}
        </Stack>
      </Modal>
    </Stack>
  );
};
