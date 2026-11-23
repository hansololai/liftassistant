import React, { useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Collapse,
  ActionIcon,
  ThemeIcon,
  Box,
  Divider,
  Tooltip,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconClock,
  IconCar,
  IconSwimming,
  IconUserExclamation,
  IconCheck,
  IconRefresh,
} from '@tabler/icons-react';
import { ConflictItem } from '../types';

interface Props {
  conflicts: ConflictItem[];
  onResolve: (id: string) => void;
  onReschedule: (id: string) => void;
  onRecheck?: () => void | Promise<void>;
  isRechecking?: boolean;
}

export const ConflictTriageCenter: React.FC<Props> = ({
  conflicts,
  onResolve,
  onReschedule,
  onRecheck,
  isRechecking = false,
}) => {
  const [opened, setOpened] = useState(true);

  if (conflicts.length === 0) {
    return (
      <Card withBorder radius="md" p="sm" bg="teal.0" style={{ borderColor: 'var(--mantine-color-teal-3)' }}>
        <Group justify="space-between">
          <Group gap="xs">
            <ThemeIcon color="teal" size="md" radius="xl">
              <IconCheck size={16} />
            </ThemeIcon>
            <Text size="sm" fw={600} c="teal.9">
              All clear! Zero schedule or facility conflicts detected for today.
            </Text>
          </Group>
          <Group gap="xs">
            {onRecheck && (
              <Tooltip label="Recheck schedule & YMCA">
                <ActionIcon
                  size="sm"
                  variant="light"
                  color="teal"
                  loading={isRechecking}
                  onClick={onRecheck}
                  aria-label="Recheck schedule"
                >
                  <IconRefresh size={14} />
                </ActionIcon>
              </Tooltip>
            )}
            <Badge color="teal" variant="light">All Clear</Badge>
          </Group>
        </Group>
      </Card>
    );
  }

  const getConflictIcon = (type: string) => {
    switch (type) {
      case 'FACILITY_MUTEX':
        return <IconSwimming size={18} />;
      case 'TRAVEL_BUFFER':
        return <IconCar size={18} />;
      case 'PERSON_OVERLAP':
        return <IconUserExclamation size={18} />;
      default:
        return <IconClock size={18} />;
    }
  };

  const getBadgeColor = (type: string) => {
    switch (type) {
      case 'FACILITY_MUTEX':
        return 'red';
      case 'TRAVEL_BUFFER':
        return 'orange';
      case 'PERSON_OVERLAP':
        return 'grape';
      default:
        return 'yellow';
    }
  };

  return (
    <Card withBorder radius="md" p="md" bg="red.0" style={{ borderColor: 'var(--mantine-color-red-3)' }}>
      <Group justify="space-between" mb={opened ? 'sm' : 0}>
        <Group gap="xs">
          <ThemeIcon color="red" size="md" radius="xl">
            <IconAlertTriangle size={18} />
          </ThemeIcon>
          <Box>
            <Text fw={700} size="sm" c="red.9">
              {conflicts.length} Schedule {conflicts.length === 1 ? 'Conflict' : 'Conflicts'} Detected
            </Text>
            <Text size="xs" c="dimmed">
              Requires review or 1-click reschedule to avoid overlapping commitments
            </Text>
          </Box>
        </Group>
        <Group gap="xs">
          {onRecheck && (
            <Tooltip label="Recheck YMCA schedule & overlapping events" position="bottom" withArrow>
              <ActionIcon
                size="sm"
                variant="white"
                color="red"
                loading={isRechecking}
                onClick={onRecheck}
                aria-label="Recheck conflicts"
              >
                <IconRefresh size={14} />
              </ActionIcon>
            </Tooltip>
          )}
          <Badge color="red" variant="filled" size="sm">
            {conflicts.length} Pending
          </Badge>
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={() => setOpened((o) => !o)}
            title={opened ? 'Collapse' : 'Expand'}
          >
            {opened ? <IconChevronUp size={18} /> : <IconChevronDown size={18} />}
          </ActionIcon>
        </Group>
      </Group>

      <Collapse in={opened}>
        <Divider my="sm" color="red.2" />
        <Stack gap="sm">
          {conflicts.map((conflict) => (
            <Card key={conflict.id} withBorder radius="sm" p="sm" bg="white" shadow="xs">
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Group gap="xs" align="flex-start">
                  <ThemeIcon color={getBadgeColor(conflict.conflict_type)} variant="light" size="md" radius="md">
                    {getConflictIcon(conflict.conflict_type)}
                  </ThemeIcon>
                  <Box>
                    <Group gap="xs" mb={2}>
                      <Text fw={600} size="sm">
                        {conflict.event_title}
                      </Text>
                      <Badge size="xs" color={getBadgeColor(conflict.conflict_type)} variant="light">
                        {conflict.conflict_type.replace('_', ' ')}
                      </Badge>
                    </Group>
                    <Text size="xs" c="dark.3" fw={500}>
                      {conflict.title}
                    </Text>
                    <Text size="xs" c="dimmed" mt={2}>
                      {conflict.description}
                    </Text>
                  </Box>
                </Group>
              </Group>

              <Group justify="flex-end" gap="xs" mt="sm">
                {onRecheck && (
                  <Tooltip label="Recheck conflict">
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color="gray"
                      loading={isRechecking}
                      onClick={onRecheck}
                      aria-label="Recheck"
                    >
                      <IconRefresh size={13} />
                    </ActionIcon>
                  </Tooltip>
                )}
                <Button
                  size="compact-xs"
                  variant="light"
                  color="gray"
                  onClick={() => onResolve(conflict.id)}
                >
                  Keep
                </Button>
                <Button
                  size="compact-xs"
                  variant="filled"
                  color="blue"
                  onClick={() => onReschedule(conflict.id)}
                >
                  {conflict.suggested_action}
                </Button>
              </Group>
            </Card>
          ))}
        </Stack>
      </Collapse>
    </Card>
  );
};
