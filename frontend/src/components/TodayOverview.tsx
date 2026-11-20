import React, { useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  ThemeIcon,
  Box,
  Paper,
  Collapse,
  ActionIcon,
  Button,
} from '@mantine/core';
import {
  IconSun,
  IconClock,
  IconMapPin,
  IconUser,
  IconHourglassEmpty,
  IconChevronDown,
  IconChevronUp,
  IconCheck,
  IconTrash,
} from '@tabler/icons-react';
import { EventItem, QuickTemplate, SnapIntent } from '../types';
import { QuickActionBar } from './QuickActionBar';
import { EventCard } from './EventCard';

interface Props {
  templates: QuickTemplate[];
  events: EventItem[];
  onSaveQuickEvent: (event: Partial<EventItem>) => void;
  onSnapReceipt: (intent: SnapIntent, details?: Partial<EventItem>) => void;
  onNavigateTab?: (tab: any) => void;
  onSelectEvent?: (event: EventItem) => void;
  onToggleComplete?: (eventId: string) => void;
}

export const TodayOverview: React.FC<Props> = ({
  templates,
  events,
  onSaveQuickEvent,
  onSnapReceipt,
  onNavigateTab,
  onSelectEvent,
  onToggleComplete,
}) => {
  const [expandedDeadlines, setExpandedDeadlines] = useState(false);

  // Determine current day string in local time (YYYY-MM-DD)
  const todayDateStr = new Date().toLocaleDateString('en-CA'); // e.g. "2026-11-16"
  // For demo/mock resilience, also match the mock date if user is playing with mock seeds
  const isTargetDate = (dStr?: string) => {
    if (!dStr) return false;
    return dStr.startsWith(todayDateStr) || dStr.startsWith('2026-11-09');
  };

  // Helper to determine if an event is a long-horizon deadline obligation (e.g. tax return, property tax, inspection)
  const isLongDeadlineEvent = (e: EventItem): boolean => {
    if (!e.deadline) return false;
    const deadlineDate = new Date(e.deadline);
    const now = new Date();
    const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);

    // Due on a future date beyond today
    if (deadlineDate > todayEnd) {
      return true;
    }

    // Or scheduled and deadline are separated by 24+ hours
    if (e.scheduled_at) {
      const scheduledDate = new Date(e.scheduled_at);
      const diffHours = (deadlineDate.getTime() - scheduledDate.getTime()) / (1000 * 60 * 60);
      if (diffHours >= 24) return true;
    }

    return false;
  };

  // Filter for today's events (both scheduled and completed today, including quick logged activities)
  const todayEvents = events
    .filter((e) => {
      // Exclude long multi-day/distant deadline obligations from today's timeline
      if (isLongDeadlineEvent(e)) return false;

      // Include if scheduled today or completed today
      const isSchedToday = isTargetDate(e.scheduled_at);
      const isCompletedToday = isTargetDate(e.completed_at);
      return isSchedToday || isCompletedToday;
    })
    .sort((a, b) => {
      const timeA = new Date(a.scheduled_at || a.completed_at || 0).getTime();
      const timeB = new Date(b.scheduled_at || b.completed_at || 0).getTime();
      return timeA - timeB;
    });

  // Today's completed count
  const todayCompletedCount = todayEvents.filter((e) => !!e.completed_at).length;
  const todayScheduledCount = todayEvents.length - todayCompletedCount;

  // Extract uncompleted events with long deadlines, sorted by closest deadline
  const upcomingDeadlines = events
    .filter((e) => e.deadline && !e.completed_at && isLongDeadlineEvent(e))
    .sort((a, b) => new Date(a.deadline!).getTime() - new Date(b.deadline!).getTime());

  const nearestDeadline = upcomingDeadlines[0];

  const getDaysUntil = (deadlineStr: string) => {
    const diff = new Date(deadlineStr).getTime() - new Date().setHours(0, 0, 0, 0);
    return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
  };

  return (
    <Stack gap="md">
      {/* 1. Morning Briefing Card (Compact Mobile Inline with Expandable 1-Line Deadlines) */}
      <Card withBorder radius="md" p="xs" bg="blue.0" style={{ borderColor: 'var(--mantine-color-blue-2)' }}>
        <Group justify="space-between" align="center" wrap="nowrap" mb={4}>
          <Group gap={6} wrap="nowrap" align="center" style={{ overflow: 'hidden' }}>
            <IconSun size={17} color="#1c7ed6" style={{ flexShrink: 0 }} />
            <Text fw={700} size="sm" c="blue.9" truncate>
              Monday Briefing
            </Text>
            <Text size="xs" c="dimmed" truncate visibleFrom="xs">
              • Nov 9 • Cranberry (52°F, Partly Cloudy)
            </Text>
          </Group>
          <Badge color="blue" variant="light" size="xs" style={{ flexShrink: 0 }}>
            52°F • Nov 9
          </Badge>
        </Group>

        <Text size="xs" c="dark.4" style={{ lineHeight: 1.35 }}>
          🏊 <b>YMCA Advisory:</b> Warm Water Pool reserved for Aerobics until 5:00 PM. Open Family Swim starts at 5:00 PM.
        </Text>

        {/* 1-Line Expandable Deadline Row inside Morning Briefing */}
        {nearestDeadline && (
          <Box mt={6} pt={5} style={{ borderTop: '1px dashed var(--mantine-color-blue-2)' }}>
            {/* Primary / Nearest Deadline Line */}
            <Group justify="space-between" align="center" wrap="nowrap">
              <Group gap={6} wrap="nowrap" style={{ overflow: 'hidden', minWidth: 0, flex: 1 }}>
                <IconHourglassEmpty size={14} color="#e03131" style={{ flexShrink: 0 }} />
                <Text size="xs" c="dark.4" truncate>
                  <Text span fw={700} c="red.8">Deadline:</Text> {nearestDeadline.title}
                </Text>
              </Group>

              <Group gap={5} wrap="nowrap" style={{ flexShrink: 0 }}>
                <Badge
                  color={getDaysUntil(nearestDeadline.deadline!) <= 7 ? 'red' : 'orange'}
                  variant="light"
                  size="xs"
                >
                  Due {new Date(nearestDeadline.deadline!).toLocaleDateString([], { month: 'short', day: 'numeric' })} ({getDaysUntil(nearestDeadline.deadline!)}d)
                </Badge>

                {upcomingDeadlines.length > 1 && (
                  <Badge
                    color="blue"
                    variant="subtle"
                    size="xs"
                    style={{ cursor: 'pointer', padding: '0 4px', fontWeight: 600 }}
                    onClick={() => setExpandedDeadlines((prev) => !prev)}
                  >
                    {expandedDeadlines ? 'Less ▲' : `+${upcomingDeadlines.length - 1} more ▼`}
                  </Badge>
                )}
              </Group>
            </Group>

            {/* Expandable list of all other one-line deadline events */}
            <Collapse in={expandedDeadlines}>
              <Stack gap={4} mt={5} pt={4} style={{ borderTop: '1px dotted var(--mantine-color-blue-1)' }}>
                {upcomingDeadlines.slice(1).map((item) => (
                  <Group key={item.id} justify="space-between" align="center" wrap="nowrap">
                    <Group gap={6} wrap="nowrap" style={{ overflow: 'hidden', minWidth: 0, flex: 1 }}>
                      <IconHourglassEmpty size={14} color="#fa5252" style={{ flexShrink: 0 }} />
                      <Text size="xs" c="dark.4" truncate>
                        <Text span fw={600} c="red.7">Deadline:</Text> {item.title}
                      </Text>
                    </Group>
                    <Badge
                      color={getDaysUntil(item.deadline!) <= 7 ? 'red' : 'orange'}
                      variant="light"
                      size="xs"
                      style={{ flexShrink: 0 }}
                    >
                      Due {new Date(item.deadline!).toLocaleDateString([], { month: 'short', day: 'numeric' })} ({getDaysUntil(item.deadline!)}d)
                    </Badge>
                  </Group>
                ))}
              </Stack>
            </Collapse>
          </Box>
        )}
      </Card>

      {/* 2. Quick Action Bar (with scrollable pills & drawer) */}
      <QuickActionBar
        templates={templates}
        onSaveQuickEvent={onSaveQuickEvent}
        onSnapReceipt={onSnapReceipt}
      />

      {/* 3. Today's Timeline (Scheduled and completed activities today) */}
      <Card withBorder radius="md" p="md">
        <Group justify="space-between" mb="sm">
          <Box>
            <Text fw={700} size="sm">
              Today's Timeline
            </Text>
            <Text size="11px" c="dimmed">
              Scheduled agenda & completed activities across family members
            </Text>
          </Box>
          <Group gap={6}>
            {todayCompletedCount > 0 && (
              <Badge variant="light" size="xs" color="teal">
                ✓ {todayCompletedCount} Done
              </Badge>
            )}
            <Badge variant="light" size="xs" color="blue">
              {todayScheduledCount} Scheduled
            </Badge>
          </Group>
        </Group>

        <Stack gap="xs">
          {todayEvents.length === 0 ? (
            <Paper p="md" withBorder radius="md" bg="gray.0" style={{ textAlign: 'center' }}>
              <Text size="xs" c="dimmed">
                No events scheduled for today. Enjoy the open day!
              </Text>
            </Paper>
          ) : (
            todayEvents.map((evt) => (
              <EventCard
                key={evt.id}
                event={evt}
                onSelectEvent={onSelectEvent}
                onToggleComplete={onToggleComplete}
                showDateInTimeLine={false}
              />
            ))
          )}
        </Stack>
      </Card>
    </Stack>
  );
};
