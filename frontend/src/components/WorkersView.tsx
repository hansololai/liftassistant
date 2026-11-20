import React, { useEffect, useMemo, useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Paper,
  Box,
  SimpleGrid,
  ThemeIcon,
  Divider,
  Modal,
  Table,
  SegmentedControl,
  ActionIcon,
  Tooltip,
  Loader,
  Alert,
  ScrollArea,
  Code,
  Textarea,
} from '@mantine/core';
import {
  IconRobot,
  IconCpu,
  IconRepeat,
  IconMail,
  IconMapPin,
  IconShoppingCart,
  IconClock,
  IconCheck,
  IconAlertTriangle,
  IconAlertCircle,
  IconRefresh,
  IconPlayerPlay,
  IconHistory,
  IconRotateClockwise,
  IconInfoCircle,
  IconEye,
  IconFileCode,
  IconSparkles,
  IconExternalLink,
  IconCalendar,
  IconTrash,
} from '@tabler/icons-react';
import { apiClient } from '../api/client';
import {
  EmailWorkerStatus,
  GeneratorRunItem,
} from '../types';

interface Props {
  onSelectEvent?: (event: any) => void;
  onRefreshEvents?: () => Promise<void> | void;
}

export const WorkersView: React.FC<Props> = ({
  onSelectEvent,
  onRefreshEvents,
}) => {
  // Worker Orchestration & Runs State
  const [workerStatus, setWorkerStatus] = useState<EmailWorkerStatus | null>(null);
  const [runs, setRuns] = useState<GeneratorRunItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [historyFilter, setHistoryFilter] = useState<string>('ALL');
  const [inspectRun, setInspectRun] = useState<GeneratorRunItem | null>(null);
  const [inspectEvents, setInspectEvents] = useState<any[]>([]);
  const [inspectExistingEvents, setInspectExistingEvents] = useState<any[]>([]);
  const [inspectFeedbacks, setInspectFeedbacks] = useState<any[]>([]);
  const [inspectTab, setInspectTab] = useState<'events' | 'emails'>('events');
  const [loadingInspectEvents, setLoadingInspectEvents] = useState(false);
  const [auditFilter, setAuditFilter] = useState<'ACTIONABLE' | 'ALL'>('ALL');

  // Event Correction / Removal State (Teach AI)
  const [selectedEventForRemove, setSelectedEventForRemove] = useState<{ id: string; title: string } | null>(null);
  const [removeReason, setRemoveReason] = useState('');
  const [isRemovingEvent, setIsRemovingEvent] = useState(false);

  const fetchWorkerData = async () => {
    setIsLoading(true);
    try {
      const [statusRes, runsRes] = await Promise.all([
        apiClient.getEmailWorkerStatus().catch(() => null),
        apiClient.listAllGeneratorRuns(undefined, 60).catch(() => []),
      ]);
      if (statusRes) {
        setWorkerStatus(statusRes);
      }
      setRuns(runsRes);
    } catch (err: any) {
      console.warn('Failed to load worker status:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const refreshRunsSilently = async () => {
    try {
      const [statusRes, runsRes] = await Promise.all([
        apiClient.getEmailWorkerStatus().catch(() => null),
        apiClient.listAllGeneratorRuns(undefined, 60).catch(() => []),
      ]);
      if (statusRes) setWorkerStatus(statusRes);
      if (runsRes && runsRes.length > 0) setRuns(runsRes);
      if (onRefreshEvents) void onRefreshEvents();
    } catch {
      // silent background poll
    }
  };

  useEffect(() => {
    void fetchWorkerData();
  }, []);

  // Auto-poll runs every 2s when any worker is actively RUNNING in the background
  useEffect(() => {
    const hasRunningRun = runs.some((r) => r.status === 'RUNNING');
    if (!hasRunningRun) return;

    const interval = setInterval(() => {
      void refreshRunsSilently();
    }, 2000);

    return () => clearInterval(interval);
  }, [runs]);

  useEffect(() => {
    if (!inspectRun) {
      setInspectEvents([]);
      setInspectExistingEvents([]);
      setInspectFeedbacks([]);
      setInspectTab('events');
      return;
    }
    // Pre-populate with inspectRun.generated_events if present
    if (inspectRun.generated_events && inspectRun.generated_events.length > 0) {
      setInspectEvents(inspectRun.generated_events);
    }
    if ((inspectRun as any).existing_events && (inspectRun as any).existing_events.length > 0) {
      setInspectExistingEvents((inspectRun as any).existing_events);
    }
    // Fetch full run traceability details from API
    setLoadingInspectEvents(true);
    apiClient
      .getGeneratorRunResult(inspectRun.id)
      .then((res: any) => {
        if (res.events) {
          setInspectEvents(res.events);
        }
        if (res.existing_events) {
          setInspectExistingEvents(res.existing_events);
        }
        if (res.feedbacks) {
          setInspectFeedbacks(res.feedbacks);
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch detailed run events:', err);
      })
      .finally(() => {
        setLoadingInspectEvents(false);
      });
  }, [inspectRun]);

  // Action Handlers
  const handleRunMasterAll = async () => {
    setActionInProgress('MASTER');
    setStatusMessage(null);
    try {
      await apiClient.triggerMasterDailyRun();
      setStatusMessage({
        type: 'info',
        text: 'Master Daily Run started in background across all 4 workers (RUNNING).',
      });
      void refreshRunsSilently();
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Master run failed to start: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRetryFailed = async () => {
    setActionInProgress('RETRY_FAILED');
    setStatusMessage(null);
    try {
      const res = await apiClient.triggerMasterRetryFailed();
      setStatusMessage({
        type: res.retried_count > 0 ? 'info' : 'info',
        text: res.message,
      });
      void refreshRunsSilently();
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Retry failed: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRunCalendarWorker = async () => {
    setActionInProgress('CALENDAR_RULE_WORKER');
    setStatusMessage(null);
    try {
      const res = await apiClient.triggerCalendarRuleWorkerRun();
      if (res.run) {
        setRuns((prev) => [res.run, ...prev.filter((r) => r.id !== res.run.id)]);
      }
      setStatusMessage({
        type: 'info',
        text: 'Calendar Rule Worker: Started in background (Status: RUNNING)',
      });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Calendar worker failed to start: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRunEmailWorker = async () => {
    setActionInProgress('EMAIL_EVENT_WORKER');
    setStatusMessage(null);
    try {
      const res = await apiClient.triggerEmailGeneratorRun();
      const run = (res as any).run || res;
      if (run && run.id) {
        setRuns((prev) => [run, ...prev.filter((r) => r.id !== run.id)]);
      }
      setStatusMessage({
        type: 'info',
        text: 'Email Perception Worker: Started in background (Status: RUNNING)',
      });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Email worker failed to start: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRunFacilityWorker = async () => {
    setActionInProgress('FACILITY_CLOSURE_WORKER');
    setStatusMessage(null);
    try {
      const res = await apiClient.triggerFacilityWorkerRun();
      if (res.run) {
        setRuns((prev) => [res.run, ...prev.filter((r) => r.id !== res.run.id)]);
      }
      setStatusMessage({
        type: 'info',
        text: 'Facility Closure Worker: Started in background (Status: RUNNING)',
      });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Facility worker failed to start: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRunDepletionWorker = async () => {
    setActionInProgress('INVENTORY_DEPLETION_WORKER');
    setStatusMessage(null);
    try {
      const res = await apiClient.triggerDepletionWorkerRun();
      if (res.run) {
        setRuns((prev) => [res.run, ...prev.filter((r) => r.id !== res.run.id)]);
      }
      setStatusMessage({
        type: 'info',
        text: 'Inventory Depletion Worker: Started in background (Status: RUNNING)',
      });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `Depletion worker failed to start: ${err?.message || err}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRetrySingleRun = async (run: GeneratorRunItem) => {
    const type = run.generator_type;
    if (type.includes('CALENDAR')) {
      await handleRunCalendarWorker();
    } else if (type.includes('EMAIL')) {
      await handleRunEmailWorker();
    } else if (type.includes('FACILITY')) {
      await handleRunFacilityWorker();
    } else if (type.includes('DEPLETION')) {
      await handleRunDepletionWorker();
    }
  };

  const handleConfirmRemoveEvent = async () => {
    if (!selectedEventForRemove?.id) return;
    setIsRemovingEvent(true);
    try {
      await apiClient.submitEmailEventFeedback({
        event_id: selectedEventForRemove.id,
        status: 'REMOVED',
        user_correction_reason: removeReason.trim() || 'User marked event as incorrectly generated.',
        run_id: inspectRun?.id,
      });
      // Refresh inspect details from server to ensure appended feedback & audit trail are updated
      if (inspectRun) {
        try {
          const fresh = await apiClient.getGeneratorRunResult(inspectRun.id);
          if (fresh.events) setInspectEvents(fresh.events);
          if (fresh.feedbacks) setInspectFeedbacks(fresh.feedbacks);
          if (fresh.run) {
            setInspectRun(fresh.run);
            setRuns((prev) =>
              prev.map((r) => (r.id === fresh.run.id ? { ...r, created_count: fresh.run.created_count } : r))
            );
          }
        } catch {
          // Fallback to local filtering
          setInspectEvents((prev) => prev.filter((e) => e.id !== selectedEventForRemove.id));
          setInspectFeedbacks((prev) =>
            prev.map((fb) =>
              fb.event_id === selectedEventForRemove.id
                ? {
                    ...fb,
                    status: 'REMOVED',
                    user_correction_reason: `Deleted event '${selectedEventForRemove.title}' with prompt reason: '${removeReason.trim()}'`,
                  }
                : fb
            )
          );
        }
      }
      setStatusMessage({
        type: 'success',
        text: `Deleted "${selectedEventForRemove.title}", updated previous run feedback audit, and added AI prompt rule!`,
      });
      setSelectedEventForRemove(null);
      setRemoveReason('');
      void fetchWorkerData();
      if (onRefreshEvents) void onRefreshEvents();
    } catch (err: any) {
      alert(`Failed to delete event: ${err?.message || err}`);
    } finally {
      setIsRemovingEvent(false);
    }
  };

  // Filtered runs for table
  const filteredRuns = useMemo(() => {
    if (historyFilter === 'ALL') return runs;
    return runs.filter((r) => {
      const g = r.generator_type;
      if (historyFilter === 'CALENDAR') return g.includes('CALENDAR');
      if (historyFilter === 'EMAIL') return g.includes('EMAIL');
      if (historyFilter === 'FACILITY') return g.includes('FACILITY');
      if (historyFilter === 'DEPLETION') return g.includes('DEPLETION');
      return true;
    });
  }, [runs, historyFilter]);

  const actionableAuditCount = useMemo(
    () =>
      inspectFeedbacks.filter(
        (f) =>
          (f.event_id && (String(f.event_id).startsWith('evt_') || String(f.event_id).startsWith('cls_'))) ||
          f.llm_category === 'EXISTING' ||
          f.user_status === 'PENDING'
      ).length,
    [inspectFeedbacks]
  );

  const filteredAuditFeedbacks = useMemo(() => {
    if (auditFilter === 'ACTIONABLE') {
      return inspectFeedbacks.filter(
        (f) =>
          (f.event_id && (String(f.event_id).startsWith('evt_') || String(f.event_id).startsWith('cls_'))) ||
          f.llm_category === 'EXISTING' ||
          f.user_status === 'PENDING'
      );
    }
    return inspectFeedbacks;
  }, [inspectFeedbacks, auditFilter]);

  // Sub-worker latest status helpers
  const getSubWorkerInfo = (key: string) => {
    const fromStatus = workerStatus?.workers?.[key];
    if (fromStatus) {
      return {
        status: fromStatus.latest_status || 'IDLE',
        lastRunAt: fromStatus.latest_run_at,
        createdCount: fromStatus.created_count ?? 0,
        errorMessage: fromStatus.error_message,
      };
    }
    // Fallback search through runs
    const latest = runs.find((r) => r.generator_type === key || r.generator_type.includes(key.split('_')[0]));
    if (latest) {
      return {
        status: latest.status,
        lastRunAt: latest.started_at,
        createdCount: latest.created_count,
        errorMessage: latest.error_message,
      };
    }
    return { status: 'IDLE', lastRunAt: undefined, createdCount: 0, errorMessage: undefined };
  };

  const formatRunTimestamp = (isoStr?: string) => {
    if (!isoStr) return 'Never';
    const d = new Date(isoStr);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (isToday) {
      return `Today at ${timeStr}`;
    }
    const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    return `${dateStr}, ${timeStr}`;
  };

  const calWorker = getSubWorkerInfo('CALENDAR_RULE_WORKER');
  const emailWorker = getSubWorkerInfo('EMAIL_EVENT_WORKER');
  const facilityWorker = getSubWorkerInfo('FACILITY_CLOSURE_WORKER');
  const depletionWorker = getSubWorkerInfo('INVENTORY_DEPLETION_WORKER');

  const hasFailedWorkers = [calWorker, emailWorker, facilityWorker, depletionWorker].some((w) => w.status === 'FAILED');

  return (
    <Stack gap="md">
      {statusMessage && (
        <Alert
          color={statusMessage.type === 'error' ? 'red' : statusMessage.type === 'success' ? 'green' : 'blue'}
          title={statusMessage.type === 'error' ? 'Execution Notice' : 'Success'}
          withCloseButton
          onClose={() => setStatusMessage(null)}
          icon={statusMessage.type === 'error' ? <IconAlertCircle size={16} /> : <IconCheck size={16} />}
        >
          {statusMessage.text}
        </Alert>
      )}

      {/* ============================================================ */}
      {/* 1. MASTER DAILY ORCHESTRATOR BANNER                          */}
      {/* ============================================================ */}
      <Card withBorder radius="md" p="md" bg="indigo.0" style={{ borderColor: 'var(--mantine-color-indigo-2)' }}>
            <Group justify="space-between" align="center" wrap="wrap" gap="md">
              <Box>
                <Group gap="xs" mb={4}>
                  <ThemeIcon size="md" radius="md" color="indigo" variant="filled">
                    <IconRobot size={18} />
                  </ThemeIcon>
                  <Text size="md" fw={800} c="indigo.9">
                    Master Daily Life Worker
                  </Text>
                  <Badge
                    size="sm"
                    color={
                      workerStatus?.is_worker_running || workerStatus?.is_running !== false ? 'teal' : 'gray'
                    }
                    variant="filled"
                  >
                    {workerStatus?.is_worker_running || workerStatus?.is_running !== false
                      ? '24h Daemon Active'
                      : 'Daemon Standby'}
                  </Badge>
                  {isLoading && <Loader size="xs" color="indigo" />}
                </Group>
                <Text size="xs" c="indigo.9">
                  Thin execution harness wrapping 4 core domain engines in isolated lifecycle blocks with failure tolerance.
                </Text>
                {workerStatus?.last_run_time && (
                  <Text size="11px" c="indigo.8" mt={4}>
                    Last Master Run: <strong>{new Date(workerStatus.last_run_time).toLocaleString()}</strong>
                    {workerStatus.next_run_time && (
                      <>
                        {' '}
                        &bull; Next Scheduled:{' '}
                        <strong>
                          {new Date(workerStatus.next_run_time).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </strong>
                      </>
                    )}
                  </Text>
                )}
              </Box>

              {/* Master Control Buttons */}
              <Group gap="xs">
                <Button
                  size="sm"
                  color="indigo"
                  variant="filled"
                  leftSection={<IconPlayerPlay size={16} />}
                  loading={actionInProgress === 'MASTER'}
                  onClick={handleRunMasterAll}
                >
                  Run All (Master)
                </Button>
                <Button
                  size="sm"
                  color="red"
                  variant={hasFailedWorkers ? 'filled' : 'light'}
                  leftSection={<IconRotateClockwise size={16} />}
                  loading={actionInProgress === 'RETRY_FAILED'}
                  onClick={handleRetryFailed}
                >
                  Retry Failed
                </Button>
                <ActionIcon
                  size="lg"
                  variant="default"
                  radius="md"
                  onClick={fetchWorkerData}
                  loading={isLoading}
                  title="Refresh status"
                >
                  <IconRefresh size={16} />
                </ActionIcon>
              </Group>
            </Group>
          </Card>

          {/* ============================================================ */}
          {/* 2. SUB-WORKERS MATRIX (4 THIN WORKERS)                       */}
          {/* ============================================================ */}
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            {/* Worker 1: CalendarRuleWorker */}
            <Card withBorder radius="md" p="md" shadow="xs">
              <Group justify="space-between" align="flex-start" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size="md" radius="md" color="teal" variant="light">
                    <IconRepeat size={18} />
                  </ThemeIcon>
                  <Box>
                    <Text fw={700} size="sm">
                      Calendar Rule Worker
                    </Text>
                    <Text size="10px" c="dimmed">
                      Engine: EventGeneratorService
                    </Text>
                  </Box>
                </Group>
                <Badge
                  size="xs"
                  color={
                    calWorker.status === 'SUCCESS' ? 'teal' : calWorker.status === 'FAILED' ? 'red' : 'gray'
                  }
                  variant="filled"
                >
                  {calWorker.status}
                </Badge>
              </Group>

              <Text size="xs" c="dark.3" mb="sm" style={{ minHeight: 34 }}>
                Evaluates recurring yearly, monthly, and weekly rules; spawns pending calendar events within configured lead-time windows.
              </Text>

              <Divider my="xs" />

              <Group justify="space-between" align="center">
                <Box>
                  <Text size="11px" c="dimmed">
                    Last Run: <strong>{formatRunTimestamp(calWorker.lastRunAt)}</strong>
                  </Text>
                  <Text size="11px" c="teal.8">
                    Spawned Events: <strong>{calWorker.createdCount}</strong>
                  </Text>
                </Box>
                <Button
                  size="xs"
                  color="teal"
                  variant="light"
                  leftSection={<IconPlayerPlay size={12} />}
                  loading={actionInProgress === 'CALENDAR_RULE_WORKER'}
                  onClick={handleRunCalendarWorker}
                >
                  Run Worker
                </Button>
              </Group>
            </Card>

            {/* Worker 2: EmailEventWorker */}
            <Card withBorder radius="md" p="md" shadow="xs">
              <Group justify="space-between" align="flex-start" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size="md" radius="md" color="blue" variant="light">
                    <IconMail size={18} />
                  </ThemeIcon>
                  <Box>
                    <Text fw={700} size="sm">
                      Email Event Worker
                    </Text>
                    <Text size="10px" c="dimmed">
                      Engine: EmailEventGenerator + ReceiptService
                    </Text>
                  </Box>
                </Group>
                <Badge
                  size="xs"
                  color={
                    emailWorker.status === 'SUCCESS' ? 'teal' : emailWorker.status === 'FAILED' ? 'red' : 'gray'
                  }
                  variant="filled"
                >
                  {emailWorker.status}
                </Badge>
              </Group>

              <Text size="xs" c="dark.3" mb="sm" style={{ minHeight: 34 }}>
                Scans recent Gmail messages via Ollama LLM. Ingests receipts directly into pantry stock and generates pending life events.
              </Text>

              <Divider my="xs" />

              <Group justify="space-between" align="center">
                <Box>
                  <Text size="11px" c="dimmed">
                    Last Run: <strong>{formatRunTimestamp(emailWorker.lastRunAt)}</strong>
                  </Text>
                  <Text size="11px" c="blue.8">
                    Extracted: <strong>{emailWorker.createdCount} events</strong>
                  </Text>
                </Box>
                <Button
                  size="xs"
                  color="blue"
                  variant="light"
                  leftSection={<IconPlayerPlay size={12} />}
                  loading={actionInProgress === 'EMAIL_EVENT_WORKER'}
                  onClick={handleRunEmailWorker}
                >
                  Run Worker
                </Button>
              </Group>
            </Card>

            {/* Worker 3: FacilityClosureWorker */}
            <Card withBorder radius="md" p="md" shadow="xs">
              <Group justify="space-between" align="flex-start" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size="md" radius="md" color="orange" variant="light">
                    <IconMapPin size={18} />
                  </ThemeIcon>
                  <Box>
                    <Text fw={700} size="sm">
                      Facility Closure Worker
                    </Text>
                    <Text size="10px" c="dimmed">
                      Engine: EventManager.scan_and_sync
                    </Text>
                  </Box>
                </Group>
                <Badge
                  size="xs"
                  color={
                    facilityWorker.status === 'SUCCESS'
                      ? 'teal'
                      : facilityWorker.status === 'FAILED'
                      ? 'red'
                      : 'gray'
                  }
                  variant="filled"
                >
                  {facilityWorker.status}
                </Badge>
              </Group>

              <Text size="xs" c="dark.3" mb="sm" style={{ minHeight: 34 }}>
                Queries active facility blackout periods (e.g. YMCA pool maintenance, holiday closures) and syncs schedule conflict flags.
              </Text>

              <Divider my="xs" />

              <Group justify="space-between" align="center">
                <Box>
                  <Text size="11px" c="dimmed">
                    Last Run: <strong>{formatRunTimestamp(facilityWorker.lastRunAt)}</strong>
                  </Text>
                  <Text size="11px" c="orange.8">
                    Conflicts Synced: <strong>{facilityWorker.createdCount}</strong>
                  </Text>
                </Box>
                <Button
                  size="xs"
                  color="orange"
                  variant="light"
                  leftSection={<IconPlayerPlay size={12} />}
                  loading={actionInProgress === 'FACILITY_CLOSURE_WORKER'}
                  onClick={handleRunFacilityWorker}
                >
                  Run Worker
                </Button>
              </Group>
            </Card>

            {/* Worker 4: InventoryDepletionWorker */}
            <Card withBorder radius="md" p="md" shadow="xs">
              <Group justify="space-between" align="flex-start" mb="xs">
                <Group gap="xs">
                  <ThemeIcon size="md" radius="md" color="grape" variant="light">
                    <IconShoppingCart size={18} />
                  </ThemeIcon>
                  <Box>
                    <Text fw={700} size="sm">
                      Inventory Depletion Worker
                    </Text>
                    <Text size="10px" c="dimmed">
                      Engine: InventoryService.evaluate_depletion
                    </Text>
                  </Box>
                </Group>
                <Badge
                  size="xs"
                  color={
                    depletionWorker.status === 'SUCCESS'
                      ? 'teal'
                      : depletionWorker.status === 'FAILED'
                      ? 'red'
                      : 'gray'
                  }
                  variant="filled"
                >
                  {depletionWorker.status}
                </Badge>
              </Group>

              <Text size="xs" c="dark.3" mb="sm" style={{ minHeight: 34 }}>
                Calculates rolling stock burn-rate across pantry inventory. Detects runway &lt; 7 days and triggers replenishment alerts.
              </Text>

              <Divider my="xs" />

              <Group justify="space-between" align="center">
                <Box>
                  <Text size="11px" c="dimmed">
                    Last Run: <strong>{formatRunTimestamp(depletionWorker.lastRunAt)}</strong>
                  </Text>
                  <Text size="11px" c="grape.8">
                    Low Stock Items: <strong>{depletionWorker.createdCount}</strong>
                  </Text>
                </Box>
                <Button
                  size="xs"
                  color="grape"
                  variant="light"
                  leftSection={<IconPlayerPlay size={12} />}
                  loading={actionInProgress === 'INVENTORY_DEPLETION_WORKER'}
                  onClick={handleRunDepletionWorker}
                >
                  Run Worker
                </Button>
              </Group>
            </Card>
          </SimpleGrid>

          {/* ============================================================ */}
          {/* 3. EXECUTION HISTORY & RUN LOGS TABLE                        */}
          {/* ============================================================ */}
          <Card withBorder radius="md" p="md">
            <Group justify="space-between" align="center" mb="sm" wrap="wrap" gap="xs">
              <Group gap="xs">
                <IconHistory size={18} />
                <Text fw={700} size="sm">
                  Worker Execution History & Audit Logs
                </Text>
                <Badge size="xs" variant="light" color="gray">
                  {filteredRuns.length} runs
                </Badge>
              </Group>

              <SegmentedControl
                size="xs"
                value={historyFilter}
                onChange={setHistoryFilter}
                data={[
                  { label: 'All', value: 'ALL' },
                  { label: 'Calendar', value: 'CALENDAR' },
                  { label: 'Email', value: 'EMAIL' },
                  { label: 'Facility', value: 'FACILITY' },
                  { label: 'Depletion', value: 'DEPLETION' },
                ]}
              />
            </Group>

            {filteredRuns.length === 0 ? (
              <Paper withBorder p="xl" style={{ textAlign: 'center' }}>
                <Text size="sm" c="dimmed">
                  No worker execution logs recorded yet. Click &quot;Run All (Master)&quot; or any individual worker button above to execute.
                </Text>
              </Paper>
            ) : (
              <ScrollArea>
                <Table striped highlightOnHover verticalSpacing="xs">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Worker / Stage</Table.Th>
                      <Table.Th>Status</Table.Th>
                      <Table.Th>Type</Table.Th>
                      <Table.Th>Started</Table.Th>
                      <Table.Th>Results</Table.Th>
                      <Table.Th style={{ textAlign: 'right' }}>Actions</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filteredRuns.map((r) => {
                      const isSuccess = r.status === 'SUCCESS';
                      const isFailed = r.status === 'FAILED';
                      let summary = '';
                      let runType = 'MANUAL';
                      let lowStockList: string[] = [];
                      if (r.details_json) {
                        try {
                          const parsed = JSON.parse(r.details_json);
                          summary = parsed.summary_message || '';
                          runType = parsed.run_type || 'MANUAL';
                          if (Array.isArray(parsed.low_stock)) {
                            lowStockList = parsed.low_stock;
                          }
                        } catch {
                          summary = '';
                        }
                      }

                      return (
                        <Table.Tr key={r.id}>
                          <Table.Td>
                            <Group gap="xs">
                              {r.generator_type.includes('CALENDAR') && <IconRepeat size={14} color="#0ca678" />}
                              {r.generator_type.includes('EMAIL') && <IconMail size={14} color="#1c7ed6" />}
                              {r.generator_type.includes('FACILITY') && <IconMapPin size={14} color="#fd7e14" />}
                              {r.generator_type.includes('DEPLETION') && <IconShoppingCart size={14} color="#ae3ec9" />}
                              <Text size="xs" fw={600}>
                                {r.generator_type.replace(/_/g, ' ')}
                              </Text>
                            </Group>
                          </Table.Td>
                          <Table.Td>
                            <Badge
                              size="xs"
                              color={isSuccess ? 'teal' : isFailed ? 'red' : 'blue'}
                              variant={r.status === 'RUNNING' ? 'light' : 'filled'}
                              leftSection={r.status === 'RUNNING' ? <Loader size={8} color="blue" /> : undefined}
                            >
                              {r.status}
                            </Badge>
                          </Table.Td>
                          <Table.Td>
                            <Badge size="xs" variant="outline" color={runType === 'SCHEDULED' ? 'indigo' : 'gray'}>
                              {runType}
                            </Badge>
                          </Table.Td>
                          <Table.Td>
                            <Text size="xs" c="dimmed">
                              {formatRunTimestamp(r.started_at)}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <Stack gap={2}>
                              <Text size="xs" fw={isFailed ? 500 : 600} c={isFailed ? 'red' : r.status === 'RUNNING' ? 'blue.7' : 'dark.9'}>
                                {r.status === 'RUNNING'
                                  ? summary || 'Executing in background...'
                                  : isFailed
                                  ? r.error_message || 'Execution error'
                                  : r.generator_type.includes('DEPLETION')
                                  ? r.created_count > 0
                                    ? `${r.created_count} low-stock item(s) detected (< 7d runway)`
                                    : 'All inventory items have healthy runway (> 7d)'
                                  : r.generator_type.includes('FACILITY')
                                  ? r.created_count > 0
                                    ? `${r.created_count} calendar conflict(s) synced`
                                    : '0 facility conflicts found'
                                  : r.generator_type.includes('CALENDAR')
                                  ? r.created_count > 0
                                    ? `${r.created_count} recurring event(s) spawned`
                                    : '0 recurring rules due'
                                  : r.created_count > 0
                                  ? `${r.created_count} event(s) generated`
                                  : summary || `Scanned: ${r.scanned_count}, 0 created`}
                              </Text>
                              {r.generator_type.includes('DEPLETION') && lowStockList.length > 0 && (
                                <Group gap={4} wrap="wrap" mt={2}>
                                  {lowStockList.map((item, idx) => (
                                    <Badge key={idx} size="xs" color="orange" variant="light">
                                      {item}
                                    </Badge>
                                  ))}
                                </Group>
                              )}
                              {r.generated_events && r.generated_events.length > 0 && (
                                <Group gap={4} wrap="wrap" mt={2}>
                                  {r.generated_events.map((evt) => (
                                    <Badge
                                      key={evt.id}
                                      size="xs"
                                      color="blue"
                                      variant="light"
                                      style={{ cursor: 'pointer' }}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setInspectRun(r);
                                      }}
                                      title={`Click to trace ${evt.id}: ${evt.title}`}
                                    >
                                      {evt.title}
                                    </Badge>
                                  ))}
                                </Group>
                              )}
                            </Stack>
                          </Table.Td>
                          <Table.Td style={{ textAlign: 'right' }}>
                            <Group gap="xs" justify="flex-end">
                              {isFailed && (
                                <Button
                                  size="compact-xs"
                                  color="red"
                                  variant="light"
                                  leftSection={<IconRotateClockwise size={12} />}
                                  onClick={() => handleRetrySingleRun(r)}
                                >
                                  Retry
                                </Button>
                              )}
                              <ActionIcon
                                size="sm"
                                variant="subtle"
                                color="gray"
                                onClick={() => setInspectRun(r)}
                                title="View details"
                              >
                                <IconEye size={14} />
                              </ActionIcon>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                      );
                    })}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            )}
          </Card>

      {/* Inspect Run Details Modal with Full Event Traceability */}
      <Modal
        opened={!!inspectRun}
        onClose={() => setInspectRun(null)}
        title={
          <Group gap="xs">
            <IconInfoCircle size={18} color="#4c6ef5" />
            <Text fw={700}>Worker Execution Traceability</Text>
            {inspectRun && (
              <Badge size="xs" color={inspectRun.status === 'SUCCESS' ? 'teal' : 'red'}>
                {inspectRun.status}
              </Badge>
            )}
          </Group>
        }
        size="xl"
      >
        {inspectRun && (
          <Stack gap="md">
            {/* 1. Run Header & Metrics */}
            <Card withBorder radius="md" p="sm" bg="gray.0">
              <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
                <Box>
                  <Text size="11px" c="dimmed">Worker</Text>
                  <Text size="xs" fw={700}>{inspectRun.generator_type.replace(/_/g, ' ')}</Text>
                </Box>
                <Box>
                  <Text size="11px" c="dimmed">Run ID</Text>
                  <Code style={{ fontSize: 11 }}>{inspectRun.id}</Code>
                </Box>
                <Box>
                  <Text size="11px" c="dimmed">Started At</Text>
                  <Text size="xs">{formatRunTimestamp(inspectRun.started_at)}</Text>
                </Box>
                <Box>
                  <Text size="11px" c="dimmed">Metrics</Text>
                  <Text size="xs" fw={600}>
                    {inspectRun.generator_type.includes('DEPLETION')
                      ? `${inspectRun.scanned_count} evaluated • ${inspectRun.created_count} low-stock`
                      : inspectRun.generator_type.includes('FACILITY')
                      ? `${inspectRun.scanned_count} closures checked • ${inspectRun.created_count} conflicts`
                      : inspectRun.generator_type.includes('EMAIL')
                      ? `${inspectRun.scanned_count} scanned (${inspectFeedbacks.length} evaluated) • ${inspectRun.created_count} created`
                      : `${inspectRun.scanned_count} scanned • ${inspectRun.created_count} created`}
                  </Text>
                </Box>
              </SimpleGrid>
            </Card>

            {/* Run Execution Summary Banner */}
            {(() => {
              let msg = '';
              try {
                const parsed = JSON.parse(inspectRun.details_json || '{}');
                msg = parsed.summary_message || '';
              } catch {}
              if (!msg && inspectRun.generator_type.includes('EMAIL')) {
                const prefiltered = Math.max(0, inspectRun.scanned_count - inspectFeedbacks.length);
                msg = `Scanned ${inspectRun.scanned_count} emails from Gmail: ${prefiltered} non-transactional pre-filtered, ${inspectFeedbacks.length} evaluated by AI. Generated ${inspectRun.created_count} events into the life ledger.`;
              }
              if (!msg) return null;
              return (
                <Paper withBorder p="xs" radius="md" bg="blue.0" style={{ borderColor: '#d0ebff' }}>
                  <Text size="xs" c="blue.9" fw={500}>
                    ℹ️ {msg}
                  </Text>
                </Paper>
              );
            })()}

            {/* 2. Sub-Tabs: Generated Events vs All Evaluated Emails */}
            {inspectFeedbacks.length > 0 && (
              <SegmentedControl
                size="xs"
                value={inspectTab}
                onChange={(val) => setInspectTab(val as 'events' | 'emails')}
                data={[
                  { label: `Generated Life Events (${inspectEvents.length})`, value: 'events' },
                  { label: `Email Evaluation Audit Trail (${inspectFeedbacks.length})`, value: 'emails' },
                ]}
              />
            )}

            {/* Content: Depletion Worker Results */}
            {inspectRun.generator_type.includes('DEPLETION') ? (
              <Box>
                <Group justify="space-between" mb="xs">
                  <Group gap="xs">
                    <IconShoppingCart size={16} color="#ae3ec9" />
                    <Text size="sm" fw={700}>
                      Pantry Runway Evaluation ({inspectRun.created_count} Low-Stock Flagged)
                    </Text>
                  </Group>
                </Group>

                <Stack gap="xs">
                  <Paper withBorder p="sm" radius="md" bg="grape.0" style={{ borderColor: '#eebefa' }}>
                    <Text size="xs" c="grape.9" fw={500}>
                      {(() => {
                        try {
                          const parsed = JSON.parse(inspectRun.details_json || '{}');
                          return parsed.summary_message || 'Pantry depletion analysis complete.';
                        } catch {
                          return 'Pantry depletion analysis complete.';
                        }
                      })()}
                    </Text>
                  </Paper>

                  {(() => {
                    let lowStock: string[] = [];
                    try {
                      const parsed = JSON.parse(inspectRun.details_json || '{}');
                      if (Array.isArray(parsed.low_stock)) lowStock = parsed.low_stock;
                    } catch {}

                    if (lowStock.length === 0) {
                      return (
                        <Paper withBorder p="md" radius="md" style={{ textAlign: 'center' }} bg="gray.0">
                          <Text size="xs" c="dimmed">
                            All evaluated pantry items currently have sufficient runway (&gt; 7 days).
                          </Text>
                        </Paper>
                      );
                    }

                    return (
                      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
                        {lowStock.map((item, idx) => (
                          <Card key={idx} withBorder radius="md" p="sm" shadow="xs">
                            <Group justify="space-between">
                              <Group gap="xs">
                                <ThemeIcon size="sm" color="orange" variant="light">
                                  <IconAlertTriangle size={14} />
                                </ThemeIcon>
                                <Text size="xs" fw={600}>
                                  {item}
                                </Text>
                              </Group>
                              <Badge size="xs" color="orange" variant="light">
                                Below Runway
                              </Badge>
                            </Group>
                          </Card>
                        ))}
                      </SimpleGrid>
                    );
                  })()}
                </Stack>
              </Box>
            ) : inspectRun.generator_type.includes('FACILITY') ? (
              <Box>
                <Group justify="space-between" mb="xs">
                  <Group gap="xs">
                    <IconMapPin size={16} color="#fd7e14" />
                    <Text size="sm" fw={700}>
                      Facility Schedule &amp; API Verification
                    </Text>
                  </Group>
                  <Badge size="xs" color="teal" variant="light">
                    GroupEx PRO Live API
                  </Badge>
                </Group>

                <Stack gap="sm">
                  <Paper withBorder p="sm" radius="md" bg="orange.0" style={{ borderColor: '#ffd8a8' }}>
                    <Text size="xs" c="orange.9" fw={500}>
                      {(() => {
                        try {
                          const parsed = JSON.parse(inspectRun.details_json || '{}');
                          return parsed.summary_message || 'Facility blackout verification completed.';
                        } catch {
                          return 'Facility blackout verification completed.';
                        }
                      })()}
                    </Text>
                  </Paper>

                  {(() => {
                    let schedule: any = null;
                    try {
                      const parsed = JSON.parse(inspectRun.details_json || '{}');
                      schedule = parsed.warm_pool_schedule;
                    } catch {}

                    if (!schedule) return null;

                    return (
                      <Card withBorder radius="md" p="sm" bg="blue.0" style={{ borderColor: '#d0ebff' }}>
                        <Group justify="space-between" mb="xs">
                          <Group gap="xs">
                            <ThemeIcon size="sm" color="blue" variant="filled">
                              <IconSparkles size={14} />
                            </ThemeIcon>
                            <Text size="xs" fw={700} c="blue.9">
                              {schedule.facility_name} &bull; {schedule.studio}
                            </Text>
                          </Group>
                          <Badge size="xs" color="blue" variant="filled">
                            Hours: {schedule.facility_hours}
                          </Badge>
                        </Group>

                        {/* Open Swim Intervals */}
                        {schedule.open_windows && schedule.open_windows.length > 0 && (
                          <Box mb="xs">
                            <Text size="11px" fw={700} c="teal.8" mb={4}>
                              🏊 Verified Open Swim Availability:
                            </Text>
                            <Group gap={6} wrap="wrap">
                              {schedule.open_windows.map((w: any, idx: number) => (
                                <Badge key={idx} size="xs" color="teal" variant="light">
                                  {w.start} &ndash; {w.end}
                                </Badge>
                              ))}
                            </Group>
                          </Box>
                        )}

                        {/* Occupied Class Windows */}
                        {schedule.occupied_windows && schedule.occupied_windows.length > 0 && (
                          <Box>
                            <Text size="11px" fw={700} c="orange.8" mb={4}>
                              🚫 Occupied Class Blackouts ({schedule.occupied_windows.length}):
                            </Text>
                            <Group gap={6} wrap="wrap">
                              {schedule.occupied_windows.map((w: any, idx: number) => (
                                <Badge key={idx} size="xs" color="orange" variant="outline" title={w.instructor ? `Instructor: ${w.instructor}` : undefined}>
                                  {w.start} &ndash; {w.end}: {w.activity}
                                </Badge>
                              ))}
                            </Group>
                          </Box>
                        )}
                      </Card>
                    );
                  })()}
                </Stack>
              </Box>
            ) : inspectTab === 'events' ? (
              <Box>
                <Group justify="space-between" mb="xs">
                  <Group gap="xs">
                    <IconCalendar size={16} color="#1c7ed6" />
                    <Text size="sm" fw={700}>
                      Generated Life Events ({inspectEvents.length})
                    </Text>
                  </Group>
                  {loadingInspectEvents && <Loader size="xs" />}
                </Group>

                {/* Idempotency Verified Banner for Already Ingested Events */}
                {inspectExistingEvents.length > 0 && (
                  <Card withBorder radius="md" p="sm" bg="cyan.0" style={{ borderColor: '#66d9e8' }} mb="xs">
                    <Group justify="space-between" mb={4}>
                      <Group gap="xs">
                        <ThemeIcon size="sm" color="cyan" variant="filled">
                          <IconSparkles size={14} />
                        </ThemeIcon>
                        <Text size="xs" fw={700} c="cyan.9">
                          ✨ Idempotency Verified: {inspectExistingEvents.length} Event{inspectExistingEvents.length > 1 ? 's' : ''} Already Present in Life Ledger
                        </Text>
                      </Group>
                      <Badge size="xs" color="cyan" variant="filled">
                        0 Duplicates Created
                      </Badge>
                    </Group>
                    <Text size="11px" c="dark.4" mb="xs">
                      The AI recognized that the following event{inspectExistingEvents.length > 1 ? 's were' : ' was'} already created in a previous run. No duplicate calendar entries were created:
                    </Text>
                    <Stack gap={6}>
                      {inspectExistingEvents.map((evt: any) => (
                        <Paper key={evt.id} withBorder p="xs" radius="sm" bg="white">
                          <Group justify="space-between" align="center" wrap="wrap" gap="xs">
                            <Box style={{ flex: 1 }}>
                              <Group gap="xs">
                                <Badge size="xs" color="indigo" variant="light">
                                  {evt.id}
                                </Badge>
                                <Text size="xs" fw={700}>
                                  {evt.title}
                                </Text>
                                <Badge size="xs" color="cyan" variant="outline">
                                  ALREADY IN LEDGER
                                </Badge>
                                {evt.total_amount && (
                                  <Badge size="xs" color="green" variant="filled">
                                    ${Number(evt.total_amount).toFixed(2)}
                                  </Badge>
                                )}
                              </Group>
                              {evt.originating_run_id && (
                                <Group gap={6} mt={2}>
                                  <Badge size="xs" color="gray" variant="light">
                                    Originating Run: {evt.originating_run_id}
                                  </Badge>
                                  {evt.originating_run_time && (
                                    <Text size="10px" c="dimmed">
                                      ({new Date(evt.originating_run_time).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })})
                                    </Text>
                                  )}
                                </Group>
                              )}
                              {evt.llm_reason && (
                                <Text size="11px" c="dimmed" mt={2}>
                                  {evt.llm_reason}
                                </Text>
                              )}
                            </Box>
                            <Group gap="xs">
                              {onSelectEvent && (
                                <Button
                                  size="compact-xs"
                                  variant="light"
                                  color="cyan"
                                  leftSection={<IconExternalLink size={12} />}
                                  onClick={() => {
                                    onSelectEvent(evt);
                                    setInspectRun(null);
                                  }}
                                >
                                  Open Event
                                </Button>
                              )}
                              <Button
                                size="compact-xs"
                                variant="light"
                                color="red"
                                leftSection={<IconTrash size={12} />}
                                onClick={() => {
                                  setSelectedEventForRemove({ id: evt.id, title: evt.title });
                                  setRemoveReason('');
                                }}
                              >
                                Delete Event
                              </Button>
                            </Group>
                          </Group>
                        </Paper>
                      ))}
                    </Stack>
                  </Card>
                )}

                {inspectEvents.length === 0 ? (
                  <Paper withBorder p="md" radius="md" style={{ textAlign: 'center' }} bg="gray.0">
                    <Text size="xs" c="dimmed">
                      {inspectExistingEvents.length > 0
                        ? `All candidate emails were either non-transactional, skipped, or already recorded in your ledger. 0 new events created.`
                        : inspectRun.scanned_count > 0
                        ? `Scanned ${inspectRun.scanned_count} item(s); 0 actionable calendar events generated (e.g. promotional emails skipped or rules not yet due).`
                        : 'No events generated during this execution run.'}
                    </Text>
                  </Paper>
                ) : (
                  <Stack gap="xs">
                    {inspectEvents.map((evt: any) => (
                      <Card key={evt.id} withBorder radius="md" p="sm" shadow="xs">
                        <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
                          <Box style={{ flex: 1 }}>
                            <Group gap="xs" mb={4}>
                              <Badge size="xs" color="indigo" variant="light">
                                {evt.id}
                              </Badge>
                              <Text size="sm" fw={700}>
                                {evt.title}
                              </Text>
                              <Badge
                                size="xs"
                                color={
                                  evt.event_type === 'SHOPPING'
                                    ? 'teal'
                                    : evt.event_type === 'BILL'
                                    ? 'red'
                                    : 'blue'
                                }
                              >
                                {evt.event_type}
                              </Badge>
                              {evt.total_amount && (
                                <Badge size="xs" color="green" variant="filled">
                                  ${Number(evt.total_amount).toFixed(2)}
                                </Badge>
                              )}
                            </Group>

                            <Group gap="md" mt={4}>
                              {evt.scheduled_at && (
                                <Group gap={4}>
                                  <IconClock size={12} color="#868e96" />
                                  <Text size="11px" c="dimmed">
                                    Scheduled: {new Date(evt.scheduled_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                                  </Text>
                                </Group>
                              )}
                              {evt.deadline && (
                                <Group gap={4}>
                                  <IconCalendar size={12} color="#fa5252" />
                                  <Text size="11px" c="red.7" fw={600}>
                                    Due / Deadline: {new Date(evt.deadline).toLocaleDateString([], { dateStyle: 'short' })}
                                  </Text>
                                </Group>
                              )}
                            </Group>

                            {(evt.llm_reason || evt.notes) && (
                              <Text size="11px" c="dimmed" mt={4} style={{ whiteSpace: 'pre-wrap' }}>
                                <strong>Trace Reason:</strong> {evt.llm_reason || evt.notes}
                              </Text>
                            )}
                          </Box>

                          <Group gap="xs">
                            <Button
                              size="compact-xs"
                              variant="light"
                              color="red"
                              leftSection={<IconTrash size={12} />}
                              onClick={() => {
                                setSelectedEventForRemove({ id: evt.id, title: evt.title });
                                setRemoveReason('');
                              }}
                            >
                              Delete Event
                            </Button>
                            {onSelectEvent && (
                              <Button
                                size="compact-xs"
                                variant="light"
                                color="blue"
                                leftSection={<IconExternalLink size={12} />}
                                onClick={() => {
                                  onSelectEvent(evt);
                                  setInspectRun(null);
                                }}
                              >
                                Open Event
                              </Button>
                            )}
                          </Group>
                        </Group>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Box>
            ) : (
              /* Content: Email Perception Audit Trail */
              <Box>
                <Group justify="space-between" mb="xs" wrap="wrap" gap="xs">
                  <Group gap="xs">
                    <IconMail size={16} color="#4c6ef5" />
                    <Text size="sm" fw={700}>
                      Perception Decision Audit Trail
                    </Text>
                  </Group>
                  <SegmentedControl
                    size="xs"
                    value={auditFilter}
                    onChange={(val) => setAuditFilter(val as any)}
                    data={[
                      { label: `Actionable (${actionableAuditCount})`, value: 'ACTIONABLE' },
                      { label: `All Evaluated (${inspectFeedbacks.length})`, value: 'ALL' },
                    ]}
                  />
                </Group>

                {filteredAuditFeedbacks.length === 0 ? (
                  <Paper withBorder p="md" radius="md" style={{ textAlign: 'center' }} bg="gray.0">
                    <Text size="xs" c="dimmed">
                      No actionable events in this run ({inspectFeedbacks.length} non-actionable emails evaluated &amp; skipped). Switch to &quot;All Evaluated&quot; to inspect skipped promotions or notices.
                    </Text>
                  </Paper>
                ) : (
                  <Stack gap="xs">
                    {filteredAuditFeedbacks.map((fb: any) => {
                    const isExisting = fb.llm_category === 'EXISTING';
                    const isGenerated = fb.event_id && String(fb.event_id).startsWith('evt_') && !isExisting;
                    const isClosure = fb.event_id && String(fb.event_id).startsWith('cls_') && !isExisting;

                    return (
                      <Card key={fb.id} withBorder radius="md" p="xs">
                        <Group justify="space-between" align="flex-start" wrap="wrap" gap="xs">
                          <Box style={{ flex: 1 }}>
                            <Group gap="xs" mb={2}>
                              <Badge
                                size="xs"
                                color={
                                  fb.user_status === 'REMOVED'
                                    ? 'red'
                                    : isExisting
                                    ? 'cyan'
                                    : isGenerated
                                    ? 'teal'
                                    : isClosure
                                    ? 'orange'
                                    : 'gray'
                                }
                                variant="filled"
                              >
                                {fb.user_status === 'REMOVED'
                                  ? 'EVENT DELETED'
                                  : isExisting
                                  ? 'ALREADY IN LEDGER'
                                  : isGenerated
                                  ? 'EVENT CREATED'
                                  : isClosure
                                  ? 'CLOSURE DETECTED'
                                  : 'SKIPPED'}
                              </Badge>
                              <Text size="xs" fw={700}>
                                {fb.email_subject || 'Email Subject'}
                              </Text>
                              <Badge size="xs" variant="outline" color={isExisting ? 'cyan' : isGenerated ? 'blue' : 'gray'}>
                                {fb.llm_category}
                              </Badge>
                            </Group>

                            <Group gap="md" mt={2}>
                              {fb.email_from && (
                                <Text size="10px" c="dimmed">
                                  From: {fb.email_from}
                                </Text>
                              )}
                              {fb.email_date && (
                                <Text size="10px" c="dimmed">
                                  Date: {fb.email_date}
                                </Text>
                              )}
                            </Group>

                            {fb.llm_reason && (
                              <Text size="11px" c="dark.3" mt={4}>
                                <strong>Decision Reason:</strong> {fb.llm_reason}
                              </Text>
                            )}

                            {fb.user_correction_reason && (
                              <Paper withBorder p="xs" radius="xs" bg="red.0" mt={6} style={{ borderColor: '#ffa8a8' }}>
                                <Text size="11px" c="red.9" fw={600}>
                                  ❌ Audit History: {fb.user_correction_reason}
                                </Text>
                              </Paper>
                            )}
                          </Box>

                          {(isGenerated || isClosure || isExisting) && fb.user_status !== 'REMOVED' && (
                            <Group gap="xs">
                              {isExisting && onSelectEvent && fb.event_id && (
                                <Button
                                  size="compact-xs"
                                  variant="light"
                                  color="cyan"
                                  leftSection={<IconExternalLink size={12} />}
                                  onClick={() => {
                                    const matched = inspectExistingEvents.find((e) => e.id === fb.event_id);
                                    if (matched) {
                                      onSelectEvent(matched);
                                      setInspectRun(null);
                                    } else {
                                      apiClient
                                        .getEvent(fb.event_id)
                                        .then((fullEvt) => {
                                          onSelectEvent(
                                            fullEvt || {
                                              id: fb.event_id,
                                              title: fb.event_title || fb.email_subject,
                                              event_type: (fb.event_type as any) || 'DINING',
                                              dining_details: { total_amount: fb.total_amount },
                                            }
                                          );
                                        })
                                        .catch(() => {
                                          onSelectEvent({
                                            id: fb.event_id,
                                            title: fb.event_title || fb.email_subject,
                                            event_type: (fb.event_type as any) || 'DINING',
                                            dining_details: { total_amount: fb.total_amount },
                                          });
                                        })
                                        .finally(() => {
                                          setInspectRun(null);
                                        });
                                    }
                                  }}
                                >
                                  View Existing Event
                                </Button>
                              )}
                              <Button
                                size="compact-xs"
                                variant="light"
                                color="red"
                                leftSection={<IconTrash size={12} />}
                                onClick={() => {
                                  setSelectedEventForRemove({
                                    id: fb.event_id,
                                    title: fb.closure_facility_name || fb.event_title || fb.email_subject || (isClosure ? 'Facility Closure' : 'Generated Event'),
                                  });
                                  setRemoveReason('');
                                }}
                              >
                                {isClosure ? 'Dismiss Closure' : 'Delete Event'}
                              </Button>
                              {isGenerated && onSelectEvent && (
                                <Button
                                  size="compact-xs"
                                  variant="light"
                                  color="blue"
                                  leftSection={<IconExternalLink size={12} />}
                                  onClick={() => {
                                    const matched = inspectEvents.find((e) => e.id === fb.event_id);
                                    if (matched) onSelectEvent(matched);
                                    setInspectRun(null);
                                  }}
                                >
                                  Open Event
                                </Button>
                              )}
                            </Group>
                          )}
                        </Group>
                      </Card>
                    );
                  })}
                </Stack>
              )}
            </Box>
            )}

            {/* 3. Error Alert if any */}
            {inspectRun.error_message && (
              <Alert color="red" title="Error Log">
                {inspectRun.error_message}
              </Alert>
            )}

            {/* 4. Raw JSON Payload (Collapsible) */}
            {inspectRun.details_json && (
              <Box>
                <Text size="11px" fw={700} c="dimmed" mb={4}>
                  Execution Details JSON:
                </Text>
                <ScrollArea h={140}>
                  <Code block style={{ fontSize: 11 }}>
                    {JSON.stringify(JSON.parse(inspectRun.details_json), null, 2)}
                  </Code>
                </ScrollArea>
              </Box>
            )}
          </Stack>
        )}
      </Modal>

      {/* Mark Incorrect / Remove Event & Teach AI Prompt Modal */}
      <Modal
        opened={!!selectedEventForRemove}
        onClose={() => setSelectedEventForRemove(null)}
        title={
          <Group gap="xs">
            <IconAlertTriangle size={18} color="#e03131" />
            <Text fw={700} size="sm" c="red.7">
              Delete Event &amp; Teach AI Prompt
            </Text>
          </Group>
        }
        radius="md"
        centered
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Deleting <strong>{selectedEventForRemove?.title}</strong> will permanently remove it from your calendar ledger, update the run feedback audit trail, and record your prompt reason so the AI never generates similar events in future runs.
          </Text>
          <Textarea
            label="Prompt Reason (Why should the AI avoid generating this event?)"
            placeholder="e.g. Monthly statements without an unpaid balance should not create events, or marketing emails from Wealthfront should be skipped..."
            value={removeReason}
            onChange={(e) => setRemoveReason(e.currentTarget.value)}
            minRows={3}
            size="xs"
            data-autofocus
          />
          <Group justify="flex-end" gap="xs" mt="sm">
            <Button
              size="xs"
              variant="default"
              onClick={() => setSelectedEventForRemove(null)}
              disabled={isRemovingEvent}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              leftSection={<IconTrash size={14} />}
              loading={isRemovingEvent}
              onClick={handleConfirmRemoveEvent}
            >
              Delete Event &amp; Add Prompt Rule
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};
