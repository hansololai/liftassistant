import React, { useEffect, useState } from 'react';
import {
  Modal,
  Title,
  Text,
  Button,
  Stack,
  Group,
  Badge,
  Paper,
  TextInput,
  ThemeIcon,
  Divider,
  ActionIcon,
  CopyButton,
  Tooltip,
  Alert,
} from '@mantine/core';
import {
  IconDeviceMobile,
  IconPlus,
  IconCopy,
  IconCheck,
  IconTrash,
  IconAlertCircle,
  IconShieldCheck,
} from '@tabler/icons-react';
import { apiClient, DeviceItem } from '../api/client';

interface Props {
  opened: boolean;
  onClose: () => void;
  currentDeviceName?: string | null;
}

export const FamilyDevicesModal: React.FC<Props> = ({
  opened,
  onClose,
  currentDeviceName,
}) => {
  const [devices, setDevices] = useState<DeviceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [newDeviceName, setNewDeviceName] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDevices = async () => {
    setLoading(true);
    try {
      const list = await apiClient.listDevices();
      setDevices(list);
    } catch (err: any) {
      console.warn('Could not load devices:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (opened) {
      void loadDevices();
    }
  }, [opened]);

  const handleCreate = async () => {
    if (!newDeviceName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await apiClient.createDevice(newDeviceName.trim());
      setNewDeviceName('');
      await loadDevices();
    } catch (err: any) {
      setError(err.message || 'Could not create device link.');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string, name: string) => {
    if (window.confirm(`Revoke access for "${name}"? It will no longer be able to access LifeAssistant.`)) {
      try {
        await apiClient.revokeDevice(id);
        await loadDevices();
      } catch (err: any) {
        setError(err.message || 'Could not revoke device.');
      }
    }
  };

  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:5173';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        <Group gap="xs">
          <ThemeIcon color="blue" size="md" radius="xl">
            <IconShieldCheck size={18} />
          </ThemeIcon>
          <Text fw={700}>Authorized Family Devices</Text>
        </Group>
      }
      size="md"
      radius="md"
    >
      <Stack gap="md">
        <Text size="xs" c="dimmed">
          Physical mobile devices authorized to access LifeAssistant. Each device holds a 10-year cryptographic session token.
        </Text>

        {error && (
          <Alert icon={<IconAlertCircle size={14} />} color="red" p="xs" radius="sm">
            {error}
          </Alert>
        )}

        <Stack gap="xs">
          {devices.map((d) => {
            const enrollUrl = `${origin}/?enroll_token=${d.enroll_token}`;
            return (
              <Paper key={d.id} p="sm" withBorder radius="sm" bg={d.is_revoked ? 'gray.0' : 'white'}>
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <Group gap="xs" align="flex-start">
                    <ThemeIcon
                      color={d.is_revoked ? 'gray' : d.is_enrolled ? 'teal' : 'blue'}
                      variant="light"
                      size="md"
                      radius="md"
                      mt={2}
                    >
                      <IconDeviceMobile size={18} />
                    </ThemeIcon>
                    <div>
                      <Group gap="xs">
                        <Text fw={600} size="sm">
                          {d.device_name}
                        </Text>
                        {d.device_name === currentDeviceName && (
                          <Badge color="blue" size="xs" variant="filled">
                            This Device
                          </Badge>
                        )}
                        <Badge
                          color={d.is_revoked ? 'gray' : d.is_enrolled ? 'teal' : 'orange'}
                          size="xs"
                          variant="light"
                        >
                          {d.is_revoked ? 'Revoked' : d.is_enrolled ? 'Active' : 'Pending'}
                        </Badge>
                      </Group>
                      {d.is_enrolled ? (
                        <Text size="11px" c="dimmed" mt={2}>
                          Last seen: {d.last_seen_at ? new Date(d.last_seen_at).toLocaleDateString() : 'Active'}
                        </Text>
                      ) : (
                        <Text size="11px" c="orange.8" mt={2}>
                          Pending enrollment via magic link
                        </Text>
                      )}
                    </div>
                  </Group>

                  {!d.is_revoked && (
                    <Group gap={4}>
                      {!d.is_enrolled && (
                        <CopyButton value={enrollUrl} timeout={2000}>
                          {({ copied, copy }) => (
                            <Tooltip label={copied ? 'Link Copied!' : 'Copy Magic Enrollment Link'}>
                              <ActionIcon color={copied ? 'teal' : 'blue'} variant="light" onClick={copy} size="sm">
                                {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                              </ActionIcon>
                            </Tooltip>
                          )}
                        </CopyButton>
                      )}
                      <Tooltip label="Revoke Device">
                        <ActionIcon
                          color="red"
                          variant="subtle"
                          size="sm"
                          onClick={() => handleRevoke(d.id, d.device_name)}
                        >
                          <IconTrash size={14} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  )}
                </Group>
              </Paper>
            );
          })}
        </Stack>

        <Divider label="Authorize Another Device (iPad / Work Phone)" labelPosition="center" />

        <Group gap="xs">
          <TextInput
            placeholder="e.g. Dad's iPad, Mom's Work Phone"
            value={newDeviceName}
            onChange={(e) => setNewDeviceName(e.currentTarget.value)}
            style={{ flex: 1 }}
            size="xs"
          />
          <Button
            size="xs"
            color="blue"
            leftSection={<IconPlus size={14} />}
            onClick={handleCreate}
            loading={creating}
          >
            Add Device
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
