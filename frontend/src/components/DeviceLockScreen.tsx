import React, { useState } from 'react';
import {
  Card,
  Title,
  Text,
  TextInput,
  Button,
  Stack,
  ThemeIcon,
  Center,
  Container,
  Alert,
  Group,
  Badge,
  Paper,
} from '@mantine/core';
import {
  IconLock,
  IconKey,
  IconDeviceMobile,
  IconAlertCircle,
  IconCheck,
} from '@tabler/icons-react';
import { apiClient } from '../api/client';

interface Props {
  onEnrolled: (deviceName: string) => void;
}

export const DeviceLockScreen: React.FC<Props> = ({ onEnrolled }) => {
  const [tokenInput, setTokenInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleEnroll = async (tokenToUse?: string) => {
    const cleanToken = (tokenToUse || tokenInput).trim();
    if (!cleanToken) {
      setError('Please enter a valid enrollment token or tap your family magic link.');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.enrollDevice(cleanToken);
      if (res.success) {
        onEnrolled(res.device_name);
      } else {
        setError(res.message || 'Enrollment failed.');
      }
    } catch (err: any) {
      setError(err.message || 'Invalid or revoked enrollment link. Please verify your link.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Center
      style={{
        minHeight: '100vh',
        background: 'var(--mantine-color-gray-1)',
        padding: '20px',
        paddingTop: 'calc(20px + env(safe-area-inset-top, 0px))',
        paddingBottom: 'calc(20px + env(safe-area-inset-bottom, 0px))',
        boxSizing: 'border-box',
      }}
    >
      <Container size="xs" style={{ width: '100%', maxWidth: 440 }}>
        <Card withBorder shadow="md" radius="lg" p="xl" bg="white">
          <Stack align="center" gap="xs" mb="md">
            <ThemeIcon size={64} radius="xl" color="blue" variant="light">
              <IconLock size={32} />
            </ThemeIcon>
            <Title order={3} ta="center" fw={800}>
              LifeAssistant Family OS
            </Title>
            <Group gap="xs">
              <Badge color="blue" variant="light" size="sm">
                Private Household System
              </Badge>
              <Badge color="gray" variant="outline" size="sm">
                Mom & Dad Only
              </Badge>
            </Group>
            <Text size="sm" c="dimmed" ta="center" mt="xs">
              This private system is restricted to authorized family devices.
            </Text>
          </Stack>

          {error && (
            <Alert icon={<IconAlertCircle size={16} />} color="red" radius="md" mb="md">
              {error}
            </Alert>
          )}

          <Paper p="sm" radius="md" bg="blue.0" mb="md" withBorder style={{ borderColor: 'var(--mantine-color-blue-2)' }}>
            <Group gap="xs" align="flex-start" wrap="nowrap">
              <ThemeIcon color="blue" size="sm" radius="xl" mt={2}>
                <IconDeviceMobile size={14} />
              </ThemeIcon>
              <Text size="xs" c="blue.9">
                <strong>First time here?</strong> Tap the magic enrollment link sent to your iMessage / SMS. Your phone will be permanently authorized automatically.
              </Text>
            </Group>
          </Paper>

          <Stack gap="sm">
            <TextInput
              label="Have an Enrollment Code?"
              placeholder="e.g. dad_enroll_... or paste link"
              leftSection={<IconKey size={16} />}
              value={tokenInput}
              onChange={(e) => setTokenInput(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleEnroll();
              }}
              size="sm"
            />
            <Button
              fullWidth
              color="blue"
              onClick={() => void handleEnroll()}
              loading={loading}
              leftSection={<IconCheck size={16} />}
            >
              Authorize This Device
            </Button>
          </Stack>

          <Text size="11px" c="dimmed" ta="center" mt="lg">
            Zero passwords required • 10-year device cryptographic binding
          </Text>
        </Card>
      </Container>
    </Center>
  );
};
