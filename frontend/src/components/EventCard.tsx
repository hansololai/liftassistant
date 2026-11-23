import React, { useState } from 'react';
import {
  Card,
  Group,
  Text,
  Badge,
  ActionIcon,
  Collapse,
  Stack,
  Box,
  Paper,
  Tooltip,
  Rating,
} from '@mantine/core';
import {
  IconCheck,
  IconCircleCheck,
  IconCircleCheckFilled,
  IconClock,
  IconMapPin,
  IconUser,
  IconChevronDown,
  IconChevronUp,
  IconPencil,
  IconHourglassEmpty,
} from '@tabler/icons-react';
import { EventItem } from '../types';
import { PersonBadge } from './PersonBadge';

interface EventCardProps {
  event: EventItem;
  onSelectEvent?: (event: EventItem) => void;
  onToggleComplete?: (eventId: string) => void;
  defaultExpanded?: boolean;
  showDateInTimeLine?: boolean;
}

const getCategoryBadgeColor = (category: string) => {
  switch (category) {
    case 'SHOPPING':
      return 'teal';
    case 'DINING':
      return 'orange';
    case 'MAINTENANCE':
      return 'grape';
    case 'COMMUTE':
      return 'cyan';
    default:
      return 'gray';
  }
};

const getDeadlineBadge = (deadline?: string) => {
  if (!deadline) return null;
  const dDate = new Date(deadline);
  const now = new Date();
  const diffDays = Math.ceil((dDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  const badgeStyle = { fontSize: '10px', height: 18, padding: '0 6px' };

  if (diffDays < 0) {
    return <Badge color="red" size="xs" variant="filled" style={badgeStyle}>Overdue ({Math.abs(diffDays)}d)</Badge>;
  } else if (diffDays === 0) {
    return <Badge color="orange" size="xs" variant="filled" style={badgeStyle}>Due Today</Badge>;
  } else if (diffDays <= 3) {
    return <Badge color="yellow" size="xs" variant="filled" style={badgeStyle}>Due in {diffDays}d</Badge>;
  }
  return (
    <Badge color="gray" size="xs" variant="light" style={badgeStyle}>
      Due {dDate.toLocaleDateString([], { month: 'short', day: 'numeric' })}
    </Badge>
  );
};

export const EventCard: React.FC<EventCardProps> = ({
  event,
  onSelectEvent,
  onToggleComplete,
  defaultExpanded = false,
  showDateInTimeLine = true,
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const isCompleted = !!event.completed_at;

  const formatScheduledTime = () => {
    if (!event.scheduled_at) {
      if (event.deadline) {
        return `Due by ${new Date(event.deadline).toLocaleDateString([], { month: 'short', day: 'numeric' })}`;
      }
      return 'Unscheduled';
    }

    const start = new Date(event.scheduled_at);
    const timeStr = start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

    let endStr = '';
    if (event.scheduled_end_at) {
      const end = new Date(event.scheduled_end_at);
      endStr = ` - ${end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
    }

    if (!showDateInTimeLine) {
      return `${timeStr}${endStr}`;
    }

    const todayStr = new Date().toDateString();
    const eventDateStr = start.toDateString();

    let datePrefix = '';
    if (todayStr === eventDateStr) {
      datePrefix = 'Today, ';
    } else {
      datePrefix = `${start.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })} • `;
    }

    return `${datePrefix}${timeStr}${endStr}`;
  };

  const amount = event.dining_details?.total_amount ?? event.shopping_details?.total_amount;

  return (
    <Card
      withBorder
      radius="md"
      p={{ base: 'xs', sm: 'sm' }}
      shadow="xs"
      bg={isCompleted ? 'gray.0' : 'white'}
      style={{
        width: '100%',
        borderColor: event.has_conflict ? 'var(--mantine-color-red-3)' : undefined,
        cursor: 'pointer',
        transition: 'background-color 150ms ease, border-color 150ms ease',
      }}
      onClick={() => setIsExpanded((prev) => !prev)}
    >
      {/* Line 1: Checkbox, Full Title (wraps naturally), Badges, & Action Icons */}
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="xs">
        <Group gap={8} wrap="nowrap" align="flex-start" style={{ minWidth: 0, flex: 1 }}>
          {onToggleComplete ? (
            <Tooltip label={isCompleted ? 'Mark incomplete' : 'Mark completed'}>
              <ActionIcon
                size="xs"
                variant="subtle"
                color={isCompleted ? 'teal' : 'gray'}
                radius="xl"
                onClick={(e: React.MouseEvent) => {
                  e.stopPropagation();
                  onToggleComplete(event.id);
                }}
                aria-label={isCompleted ? 'Mark incomplete' : 'Mark completed'}
                style={{ flexShrink: 0, marginTop: 2 }}
              >
                {isCompleted ? (
                  <IconCircleCheckFilled size={18} color="var(--mantine-color-teal-6)" />
                ) : (
                  <IconCircleCheck size={18} color="var(--mantine-color-gray-4)" />
                )}
              </ActionIcon>
            </Tooltip>
          ) : isCompleted ? (
            <Tooltip label="Completed event">
              <IconCircleCheckFilled size={18} color="var(--mantine-color-teal-6)" style={{ flexShrink: 0, marginTop: 2 }} />
            </Tooltip>
          ) : null}

          <Box style={{ minWidth: 0, flex: 1 }}>
            <Text
              fw={700}
              size="sm"
              style={{
                lineHeight: 1.35,
                wordBreak: 'break-word',
              }}
            >
              {event.title}
            </Text>

            {/* Badges Row (wraps cleanly without compressing the title) */}
            <Group gap={4} mt={3} wrap="wrap">
              <Badge
                size="xs"
                color={getCategoryBadgeColor(event.event_type)}
                variant="light"
                style={{ fontSize: '10px', height: 18, padding: '0 6px', textTransform: 'capitalize' }}
              >
                {event.event_type.replace('_', ' ').toLowerCase()}
              </Badge>

              {event.has_conflict && (
                <Badge
                  size="xs"
                  color="red"
                  variant="light"
                  style={{ fontSize: '10px', height: 18, padding: '0 6px' }}
                >
                  ⚠️ Conflict
                </Badge>
              )}

              {amount && !event.title.includes(`$${amount.toFixed(2)}`) ? (
                <Badge
                  size="xs"
                  color="teal"
                  variant="outline"
                  style={{ fontSize: '10px', height: 18, padding: '0 6px' }}
                >
                  ${amount.toFixed(2)}
                </Badge>
              ) : null}
            </Group>
          </Box>
        </Group>

        {/* Right Action Icons: Edit & Expand */}
        <Group gap={2} wrap="nowrap" style={{ flexShrink: 0, marginTop: 1 }}>
          {onSelectEvent && (
            <Tooltip label="Edit Event">
              <ActionIcon
                variant="subtle"
                color="blue"
                size="sm"
                radius="md"
                onClick={(e: React.MouseEvent) => {
                  e.stopPropagation();
                  onSelectEvent(event);
                }}
                aria-label={`Edit ${event.title}`}
              >
                <IconPencil size={15} />
              </ActionIcon>
            </Tooltip>
          )}

          <ActionIcon
            variant="subtle"
            size="sm"
            color="gray"
            radius="md"
            aria-label={isExpanded ? 'Collapse event' : 'Expand event'}
          >
            {isExpanded ? <IconChevronUp size={15} /> : <IconChevronDown size={15} />}
          </ActionIcon>
        </Group>
      </Group>

      {/* Line 2: Time, Attendees & Deadlines */}
      <Group justify="space-between" align="center" mt={3} wrap="nowrap">
        <Group gap={6} wrap="nowrap" style={{ overflow: 'hidden', minWidth: 0, flex: 1 }}>
          <IconClock size={13} color="#868e96" style={{ flexShrink: 0 }} />
          <Text size="xs" c="dimmed" fw={500} truncate>
            {formatScheduledTime()}
          </Text>
        </Group>

        <Group gap={4} wrap="nowrap" style={{ flexShrink: 0 }}>
          {/* Small human icons for Dad, Mom, Marcus */}
          {event.people_involved && event.people_involved.length > 0 && (
            <Group gap={3} wrap="nowrap">
              {event.people_involved.map((person) => (
                <PersonBadge key={person} person={person} size="xs" withLabel={false} />
              ))}
            </Group>
          )}

          {event.deadline && (
            <Group gap={4} wrap="nowrap">
              <IconHourglassEmpty size={13} color="#e03131" />
              {getDeadlineBadge(event.deadline)}
            </Group>
          )}
        </Group>
      </Group>

      {/* Expandable Details Container */}
      <Collapse in={isExpanded}>
        <Stack gap={4} mt={8} pt={6} style={{ borderTop: '1px dashed var(--mantine-color-gray-2)' }}>
          {/* Location */}
          {(event.place_name || event.place?.name) && (
            <Group gap={4} wrap="nowrap">
              <IconMapPin size={13} color="#868e96" style={{ flexShrink: 0 }} />
              <Text size="xs" c="dark.3">
                {event.place_name || event.place?.name}
                {event.studio && (
                  <Text span fw={600} c="blue.7" ml={4}>
                    • {event.studio}
                  </Text>
                )}
              </Text>
            </Group>
          )}

          {/* Attendees with human icon badges */}
          {event.people_involved && event.people_involved.length > 0 && (
            <Group gap={4} wrap="wrap" align="center">
              <Text size="xs" c="dimmed" mr={2}>People:</Text>
              {event.people_involved.map((person) => (
                <PersonBadge key={person} person={person} size="xs" withLabel={true} />
              ))}
            </Group>
          )}

          {/* Description / Notes */}
          {(event.description || event.notes) && (
            <Text size="xs" c="dark.4" mt={2}>
              {event.description || event.notes}
            </Text>
          )}

          {/* Dining Details */}
          {event.dining_details && (
            <Group gap="xs" mt={2}>
              <Rating value={event.dining_details.rating || 5} readOnly size="xs" />
              {event.dining_details.total_amount ? (
                <Text size="11px" fw={600} c="green.8">
                  ${event.dining_details.total_amount.toFixed(2)}
                </Text>
              ) : null}
            </Group>
          )}

          {/* Shopping Details */}
          {event.shopping_details && (
            <Text size="11px" c="dimmed" mt={2}>
              {event.shopping_details.pantry_updated ? 'Pantry Updated ✓' : 'Shopping Record'}
              {event.shopping_details.store_name ? ` • Store: ${event.shopping_details.store_name}` : ''}
            </Text>
          )}

          {/* Conflict Reason Callout */}
          {event.conflict_reason && (
            <Paper p="xs" radius="sm" bg="red.0" withBorder mt={4}>
              <Text size="11px" c="red.9" fw={500}>
                ⚠️ Clash: {event.conflict_reason}
              </Text>
            </Paper>
          )}
        </Stack>
      </Collapse>
    </Card>
  );
};
