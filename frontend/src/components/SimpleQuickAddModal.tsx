import React, { useState, useEffect } from 'react';
import {
  Modal,
  Stack,
  Group,
  Button,
  Text,
  TextInput,
  Badge,
  Paper,
  Box,
  Collapse,
  Textarea,
  Chip,
  Alert,
  Loader,
  Tooltip,
} from '@mantine/core';
import {
  IconClock,
  IconCheck,
  IconUser,
  IconMapPin,
  IconChevronDown,
  IconChevronUp,
  IconSparkles,
  IconAlertTriangle,
} from '@tabler/icons-react';
import { EventItem, QuickTemplate } from '../types';
import { apiClient, ConflictCheckResult } from '../api/client';

interface Props {
  opened: boolean;
  onClose: () => void;
  template: QuickTemplate | null;
  onConfirm: (eventData: Partial<EventItem>) => void;
}

const DEFAULT_COORDS = { latitude: 40.6865, longitude: -80.1081 }; // Cranberry Twp, PA default

// Helper to get formatted local datetime string: YYYY-MM-DDTHH:mm
const formatDatetimeLocal = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

export const SimpleQuickAddModal: React.FC<Props> = ({
  opened,
  onClose,
  template,
  onConfirm,
}) => {
  const [startTime, setStartTime] = useState(formatDatetimeLocal(new Date()));
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [isCustomStart, setIsCustomStart] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [coords, setCoords] = useState(DEFAULT_COORDS);

  // People involved (directly configurable)
  const [selectedPeople, setSelectedPeople] = useState<string[]>(['Marcus']);

  // Prepopulated fields
  const [location, setLocation] = useState('');
  const [placeId, setPlaceId] = useState<string | undefined>(undefined);
  const [studio, setStudio] = useState<string | undefined>(undefined);
  const [notes, setNotes] = useState('');

  // Pre-flight conflict warning
  const [conflictWarning, setConflictWarning] = useState<ConflictCheckResult | null>(null);
  const [checkingConflict, setCheckingConflict] = useState(false);

  useEffect(() => {
    if (navigator?.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setCoords({
            latitude: Number(pos.coords.latitude.toFixed(6)),
            longitude: Number(pos.coords.longitude.toFixed(6)),
          });
        },
        () => {
          setCoords(DEFAULT_COORDS);
        },
        { timeout: 3000 }
      );
    }
  }, []);

  useEffect(() => {
    if (opened && template) {
      const defaultDuration = template.default_duration_minutes || 60;
      const now = new Date();
      // Past retrospective logs (e.g. diaper) anchor to end=now, while planned sessions (swimming, etc.) anchor to now
      const isPastLog = template.id === 'tpl_diaper' || template.id === 'tpl_poop';
      const start = isPastLog
        ? new Date(now.getTime() - defaultDuration * 60000)
        : now;

      setStartTime(formatDatetimeLocal(start));
      setDurationMinutes(defaultDuration);
      setIsCustomStart(!isPastLog);
      setShowAdvanced(false);

      // Prepopulate people (Marcus by default, or Marcus + Dad for swimming, or template defaults)
      const initialPeople = template.default_people || (template.default_person ? [template.default_person] : ['Marcus']);
      setSelectedPeople(initialPeople);

      // Prepopulate location & place
      const isSwim = template.id.includes('swim') || template.id.includes('pool') || template.name.toLowerCase().includes('swim');
      const defaultPlace = template.default_place || (isSwim ? 'Rose E. Schneider Family YMCA' : 'Home (100 Main St, Cranberry Twp, PA)');
      const defaultPid = template.default_place_id || (isSwim ? 'pl_ymca' : undefined);
      const defaultStd = template.default_studio || (isSwim ? 'Warm Water Pool' : undefined);

      setLocation(defaultPlace);
      setPlaceId(defaultPid);
      setStudio(defaultStd);
      setNotes('');
      setCoords(template.default_coords || (isSwim ? { latitude: 40.7021, longitude: -80.1245 } : DEFAULT_COORDS));
      setConflictWarning(null);
    }
  }, [opened, template]);

  // Pre-flight conflict evaluation
  useEffect(() => {
    if (!opened || !template || !startTime) {
      setConflictWarning(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const parsedDate = new Date(startTime);
        if (isNaN(parsedDate.getTime())) return;

        setCheckingConflict(true);
        const res = await apiClient.checkConflict({
          scheduled_at: formatDatetimeLocal(parsedDate),
          duration_minutes: durationMinutes,
          title: template.name || 'Quick Event',
          people_involved: selectedPeople,
          place_id: placeId,
          studio: studio,
          notes: notes || template.default_description,
        });
        setConflictWarning(res);
      } catch (err) {
        console.warn('Pre-flight conflict check in SimpleQuickAddModal failed:', err);
      } finally {
        setCheckingConflict(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [opened, template, startTime, durationMinutes, selectedPeople, placeId, studio, notes]);

  // Clicking on a duration preset: sets duration and shifts start/end appropriately
  const handleSelectDurationPreset = (mins: number) => {
    setDurationMinutes(mins);
    if (!isCustomStart) {
      const now = new Date();
      const isPastLog = template?.id === 'tpl_diaper' || template?.id === 'tpl_poop';
      const start = isPastLog
        ? new Date(now.getTime() - mins * 60000)
        : now;
      setStartTime(formatDatetimeLocal(start));
    }
  };

  // User manually edits the start time
  const handleStartTimeChange = (val: string) => {
    setStartTime(val);
    setIsCustomStart(true);
  };

  // Compute end time based on start time + duration
  const getEndTime = () => {
    const s = new Date(startTime);
    if (isNaN(s.getTime())) return new Date();
    return new Date(s.getTime() + durationMinutes * 60000);
  };

  const computedEndDate = getEndTime();
  const formatTimeStr = (d: Date) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const isFuture = (() => {
    const s = new Date(startTime);
    return !isNaN(s.getTime()) && s.getTime() > Date.now();
  })();

  const handleConfirm = () => {
    if (!template) return;

    const startDate = new Date(startTime);
    const computedEnd = !isNaN(startDate.getTime())
      ? formatDatetimeLocal(new Date(startDate.getTime() + durationMinutes * 60000))
      : undefined;

    const finalDescription = notes.trim()
      ? `${template.default_description} - ${notes.trim()}`
      : template.default_description;

    onConfirm({
      title: template.name,
      event_type: template.default_category,
      scheduled_at: startTime,
      scheduled_end_at: computedEnd,
      completed_at: isFuture ? undefined : (computedEnd || formatDatetimeLocal(new Date())),
      duration_minutes: durationMinutes,
      people_involved: selectedPeople.length > 0 ? selectedPeople : [template.default_person || 'Marcus'],
      place_id: placeId,
      place_name: location,
      studio: studio,
      description: finalDescription,
      notes: finalDescription,
      latitude: coords.latitude,
      longitude: coords.longitude,
    });

    onClose();
  };

  if (!template) return null;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      closeOnClickOutside={false}
      closeOnEscape={false}
      size="sm"
      centered
      radius="lg"
      padding="md"
      title={
        <Group gap="xs">
          <Text size="26px" style={{ lineHeight: 1 }}>{template.icon}</Text>
          <Box>
            <Text fw={700} size="md">
              {template.name}
            </Text>
            <Badge size="xs" variant="light" color="teal">
              ⚡ Quick Action
            </Badge>
          </Box>
        </Group>
      }
    >
      <Stack gap="sm">
        {/* 1. PEOPLE SELECTION (Directly accessible - only need to set people and time) */}
        <Box>
          <Group justify="space-between" align="center" mb={6}>
            <Text size="xs" fw={700} c="dark.7">
              People Involved
            </Text>
            <Badge size="xs" variant="light" color="blue">
              {selectedPeople.join(', ') || 'Select people'}
            </Badge>
          </Group>
          <Chip.Group multiple value={selectedPeople} onChange={setSelectedPeople}>
            <Group gap="xs">
              <Chip value="Marcus" size="xs" variant="outline" color="blue">
                👶 Marcus
              </Chip>
              <Chip value="Dad" size="xs" variant="outline" color="blue">
                👨 Dad
              </Chip>
              <Chip value="Mom" size="xs" variant="outline" color="blue">
                👩 Mom
              </Chip>
              <Chip value="Family" size="xs" variant="outline" color="blue">
                👨‍👩‍👧‍👦 Family
              </Chip>
            </Group>
          </Chip.Group>
        </Box>

        {/* 2. TIME SELECTION (Directly accessible) */}
        <Box>
          <Group justify="space-between" align="center" mb={4}>
            <Text size="xs" fw={700} c="dark.7">
              Time & Duration
            </Text>
            {checkingConflict ? (
              <Group gap={4}>
                <Loader size={12} color="gray" />
                <Text size="10px" c="dimmed">Checking conflict...</Text>
              </Group>
            ) : conflictWarning && conflictWarning.has_conflict ? (
              <Tooltip label={conflictWarning.conflicts.map((c) => c.title).join(' • ')} multiline w={220} withArrow>
                <Badge color="red" size="xs" variant="filled" leftSection={<IconAlertTriangle size={11} />} style={{ cursor: 'pointer' }}>
                  Conflict
                </Badge>
              </Tooltip>
            ) : conflictWarning && !conflictWarning.has_conflict && startTime ? (
              <Badge color="teal" size="xs" variant="light" leftSection={<IconCheck size={11} />}>
                Clear
              </Badge>
            ) : null}
          </Group>

          {/* Time Span Indicator */}
          <Paper p="xs" radius="md" withBorder bg="teal.0" mb="xs">
            <Group justify="space-between" align="center" wrap="nowrap">
              <Group gap={6} wrap="nowrap">
                <IconClock size={16} color="var(--mantine-color-teal-7)" />
                <Text size="xs" fw={700} c="teal.9">
                  Window:
                </Text>
              </Group>
              <Badge size="sm" variant="filled" color="teal">
                {formatTimeStr(new Date(startTime))} → {formatTimeStr(computedEndDate)}
              </Badge>
            </Group>
            <Text size="11px" c="teal.8" mt={4}>
              {durationMinutes} min • {isFuture ? 'Scheduled for future' : 'Concluded / Current log'}
            </Text>
          </Paper>

          {/* Quick Duration Presets */}
          <Group gap={6} mb="xs">
            {[
              { label: '15m', mins: 15 },
              { label: '30m', mins: 30 },
              { label: '45m', mins: 45 },
              { label: '1h', mins: 60 },
              { label: '1.5h', mins: 90 },
            ].map((item) => (
              <Button
                key={item.mins}
                size="xs"
                variant={durationMinutes === item.mins ? 'filled' : 'default'}
                color={durationMinutes === item.mins ? 'teal' : undefined}
                radius="xl"
                onClick={() => handleSelectDurationPreset(item.mins)}
                style={{ height: 26, padding: '0 10px', fontSize: 11 }}
              >
                {item.label}
              </Button>
            ))}
          </Group>

          {/* Start Time Input */}
          <TextInput
            label="Start Time"
            type="datetime-local"
            value={startTime}
            onChange={(e) => handleStartTimeChange(e.currentTarget.value)}
            leftSection={<IconClock size={16} />}
            size="xs"
          />
        </Box>

        {/* 3. PRE-FLIGHT CONFLICT ALERT (Displays if pool occupied or schedule clash) */}
        {conflictWarning && conflictWarning.has_conflict && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="red"
            variant="light"
            radius="md"
            title={conflictWarning.conflicts[0]?.title || 'Conflict Detected'}
            styles={{ title: { fontSize: '12px', fontWeight: 600 }, message: { fontSize: '11px' } }}
          >
            {conflictWarning.conflicts[0]?.description || 'This event conflicts with an existing closure or class.'}
            {conflictWarning.conflicts[0]?.suggested_action && (
              <Text size="11px" c="dimmed" mt={4}>
                💡 {conflictWarning.conflicts[0].suggested_action}
              </Text>
            )}
          </Alert>
        )}

        {/* 4. PREPOPULATED INFORMATION CARD (Pre-fills all other fields) */}
        <Paper p="xs" radius="md" withBorder bg="gray.0">
          <Group justify="space-between" align="center">
            <Group gap="xs">
              <IconSparkles size={14} color="#2b8a3e" />
              <Box>
                <Text size="xs" fw={600} c="dark.7">
                  Pre-populated Fields
                </Text>
                <Text size="11px" c="dimmed">
                  📍 {location} {studio ? `(${studio})` : ''} • {template.default_category}
                </Text>
              </Box>
            </Group>
            <Button
              variant="subtle"
              size="compact-xs"
              color="gray"
              rightSection={showAdvanced ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />}
              onClick={() => setShowAdvanced(!showAdvanced)}
            >
              {showAdvanced ? 'Hide' : 'Details'}
            </Button>
          </Group>

          {/* Optional collapsible details for rare customizations */}
          <Collapse in={showAdvanced}>
            <Stack gap="xs" mt="xs" pt="xs" style={{ borderTop: '1px solid #e9ecef' }}>
              <TextInput
                label="Location / Place Name"
                size="xs"
                value={location}
                onChange={(e) => setLocation(e.currentTarget.value)}
                leftSection={<IconMapPin size={14} />}
              />
              {studio && (
                <TextInput
                  label="Studio / Room"
                  size="xs"
                  value={studio}
                  onChange={(e) => setStudio(e.currentTarget.value)}
                />
              )}
              <Textarea
                label="Notes (pre-populated)"
                size="xs"
                value={notes || template.default_description}
                onChange={(e) => setNotes(e.currentTarget.value)}
                rows={2}
              />
            </Stack>
          </Collapse>
        </Paper>

        {/* Modal Action Button */}
        <Group mt="xs">
          <Button
            color="teal"
            size="sm"
            fullWidth
            onClick={handleConfirm}
            leftSection={<IconCheck size={16} />}
          >
            {isFuture ? `Schedule ${template.name}` : `Log ${template.name}`}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
