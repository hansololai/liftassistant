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
  Select,
} from '@mantine/core';
import {
  IconClock,
  IconCheck,
  IconUser,
  IconMapPin,
  IconChevronDown,
  IconChevronUp,
  IconSparkles,
} from '@tabler/icons-react';
import { EventItem, QuickTemplate } from '../types';

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
  const [durationMinutes, setDurationMinutes] = useState(15);
  // Tracks if the user intentionally picked a custom start time that doesn't anchor to "Now"
  const [isCustomStart, setIsCustomStart] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [coords, setCoords] = useState(DEFAULT_COORDS);

  // Hidden prepopulated fields (can be edited if advanced is expanded)
  const [person, setPerson] = useState('');
  const [location, setLocation] = useState('Home (100 Main St, Cranberry Twp, PA)');
  const [notes, setNotes] = useState('');

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
      const defaultDuration = template.default_duration_minutes || 15;
      const now = new Date();
      // By default: start = now - duration, end = now
      const start = new Date(now.getTime() - defaultDuration * 60000);
      setStartTime(formatDatetimeLocal(start));
      setDurationMinutes(defaultDuration);
      setIsCustomStart(false);
      setShowAdvanced(false);
      setPerson(template.default_person || 'Marcus');
      setLocation(template.default_place || 'Home (100 Main St, Cranberry Twp, PA)');
      setNotes('');
    }
  }, [opened, template]);

  // Clicking on a duration preset: sets duration and anchors to current time (start = now - duration)
  const handleSelectDurationPreset = (mins: number) => {
    setDurationMinutes(mins);
    setIsCustomStart(false);
    const now = new Date();
    const start = new Date(now.getTime() - mins * 60000);
    setStartTime(formatDatetimeLocal(start));
  };

  // User manually edits the start time: end time becomes start + duration (not current time)
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

  const handleConfirm = () => {
    if (!template) return;

    const startDate = new Date(startTime);
    const computedEnd = !isNaN(startDate.getTime())
      ? new Date(startDate.getTime() + durationMinutes * 60000).toISOString()
      : undefined;

    const finalDescription = notes.trim()
      ? `${template.default_description} - ${notes.trim()}`
      : template.default_description;

    onConfirm({
      title: template.name,
      event_type: template.default_category,
      scheduled_at: startTime,
      scheduled_end_at: computedEnd,
      completed_at: computedEnd || new Date().toISOString(), // Done events carry completed_at
      duration_minutes: durationMinutes,
      people_involved: [person || template.default_person || 'Marcus'],
      place_name: location,
      description: finalDescription,
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
              ⚡ 1-Click Quick Add
            </Badge>
          </Box>
        </Group>
      }
    >
      <Stack gap="sm">
        {/* Time Span Indicator: Start -> End Time */}
        <Paper p="xs" radius="md" withBorder bg="teal.0">
          <Group justify="space-between" align="center" wrap="nowrap">
            <Group gap={6} wrap="nowrap">
              <IconClock size={16} color="var(--mantine-color-teal-7)" />
              <Text size="xs" fw={700} c="teal.9">
                Event Window:
              </Text>
            </Group>
            <Badge size="sm" variant="filled" color="teal">
              {formatTimeStr(new Date(startTime))} → {!isCustomStart ? `Now (${formatTimeStr(computedEndDate)})` : formatTimeStr(computedEndDate)}
            </Badge>
          </Group>
          <Text size="11px" c="teal.8" mt={4}>
            {!isCustomStart
              ? `Duration: ${durationMinutes} min • Concluded just now.`
              : `Duration: ${durationMinutes} min • Custom scheduled window.`}
          </Text>
        </Paper>

        {/* Duration Quick Presets */}
        <Box>
          <Group justify="space-between" align="center" mb={4}>
            <Text size="11px" fw={600} c="dimmed">
              Duration Preset (sets start = now - duration):
            </Text>
            <Badge size="xs" variant="light" color="teal">
              {durationMinutes} min
            </Badge>
          </Group>
          <Group gap={6}>
            {[
              { label: '5m', mins: 5 },
              { label: '10m', mins: 10 },
              { label: '15m', mins: 15 },
              { label: '30m', mins: 30 },
              { label: '45m', mins: 45 },
              { label: '1h', mins: 60 },
            ].map((item) => (
              <Button
                key={item.mins}
                size="xs"
                variant={durationMinutes === item.mins && !isCustomStart ? 'filled' : 'default'}
                color={durationMinutes === item.mins ? 'teal' : undefined}
                radius="xl"
                onClick={() => handleSelectDurationPreset(item.mins)}
                style={{ height: 26, padding: '0 10px', fontSize: 11 }}
              >
                {item.label}
              </Button>
            ))}
          </Group>
        </Box>

        {/* Start Time Input (Allows custom start time which uncouples end time from current time) */}
        <TextInput
          label="Start Time"
          description="Adjust to shift start time (end time will follow start + duration):"
          type="datetime-local"
          value={startTime}
          onChange={(e) => handleStartTimeChange(e.currentTarget.value)}
          leftSection={<IconClock size={16} />}
          size="sm"
        />

        {/* Prepopulated Information Card (Hidden in Simple View) */}
        <Paper p="xs" radius="md" withBorder bg="gray.0">
          <Group justify="space-between" align="center">
            <Group gap="xs">
              <IconSparkles size={14} color="#2b8a3e" />
              <Text size="xs" c="dimmed">
                Pre-filled: <b>{person || template.default_person}</b> • {template.default_category} • {durationMinutes}m
              </Text>
            </Group>
            <Button
              variant="subtle"
              size="compact-xs"
              color="gray"
              rightSection={showAdvanced ? <IconChevronUp size={12} /> : <IconChevronDown size={12} />}
              onClick={() => setShowAdvanced(!showAdvanced)}
            >
              {showAdvanced ? 'Hide' : 'Options'}
            </Button>
          </Group>

          {/* Optional collapsible details for rare customizations */}
          <Collapse in={showAdvanced}>
            <Stack gap="xs" mt="xs" pt="xs" style={{ borderTop: '1px solid #e9ecef' }}>
              <Select
                label="Person Involved"
                size="xs"
                data={['Marcus', 'Dad', 'Mom', 'Family']}
                value={person}
                onChange={(v) => setPerson(v || 'Marcus')}
                leftSection={<IconUser size={14} />}
              />
              <TextInput
                label="Location"
                size="xs"
                value={location}
                onChange={(e) => setLocation(e.currentTarget.value)}
                leftSection={<IconMapPin size={14} />}
              />
              <Group justify="space-between" align="center">
                <Text size="10px" c="dimmed">
                  Device GPS Coords (stored for retry/grounding):
                </Text>
                <Badge size="xs" variant="outline" color="gray">
                  {coords.latitude}, {coords.longitude}
                </Badge>
              </Group>
              <Textarea
                label="Add Note (optional)"
                placeholder="e.g. runny stool, needed cream..."
                size="xs"
                value={notes}
                onChange={(e) => setNotes(e.currentTarget.value)}
                rows={2}
              />
            </Stack>
          </Collapse>
        </Paper>

        {/* Modal Action Buttons: Full-width single action button, dismissible via X */}
        <Group mt="xs">
          <Button
            color="teal"
            size="sm"
            fullWidth
            onClick={handleConfirm}
            leftSection={<IconCheck size={16} />}
          >
            Log {template.name}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
