import React, { useState } from 'react';
import {
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Button,
  Progress,
  Paper,
  Box,
  SimpleGrid,
  ThemeIcon,
  Divider,
  Modal,
  Table,
  Checkbox,
  NumberInput,
  Select,
  Chip,
  ScrollArea,
  Alert,
  FileButton,
  ActionIcon,
  Tooltip,
} from '@mantine/core';
import {
  IconCamera,
  IconUpload,
  IconReceipt,
  IconCheck,
  IconClock,
  IconSparkles,
  IconFileCode,
  IconBuildingStore,
  IconMapPin,
  IconCalendar,
  IconShoppingCart,
  IconPlus,
  IconX,
} from '@tabler/icons-react';
import { ReceiptJob, ExtractedLineItem, ProductItem, ProductUnitConversion, StoreItemMultiplier } from '../types';
import { MOCK_STORE_ITEM_MULTIPLIERS } from '../mockData';
import { CreateProductModal } from './CreateProductModal';
import { EventModal } from './EventModal';

interface Props {
  jobs: ReceiptJob[];
  products?: ProductItem[];
  multipliers?: StoreItemMultiplier[];
  onUploadReceipt: (filename: string, type?: 'PHOTO' | 'JSON' | 'PDF' | 'CSV') => void;
  onConfirmJob?: (job: ReceiptJob, people: string[], updatePantry: boolean) => void;
  onCreateProduct?: (product: ProductItem, conversion: ProductUnitConversion) => void;
  onUpsertMultiplier?: (store: string, item: string, multiplier: number, productId?: string) => void;
}

export const ReceiptsView: React.FC<Props> = ({
  jobs,
  products = [],
  multipliers = MOCK_STORE_ITEM_MULTIPLIERS,
  onUploadReceipt,
  onConfirmJob,
  onCreateProduct,
  onUpsertMultiplier,
}) => {
  const [activeUpload, setActiveUpload] = useState(false);
  const [selectedJobForReview, setSelectedJobForReview] = useState<ReceiptJob | null>(null);
  const [selectedPeople, setSelectedPeople] = useState<string[]>(['Family']);
  const [updatePantry, setUpdatePantry] = useState(true);

  // Unlinked Item -> Create Product in Stock Modal State
  const [createProductModalOpened, setCreateProductModalOpened] = useState(false);
  const [selectedItemForCreate, setSelectedItemForCreate] = useState<{
    item: ExtractedLineItem;
    index: number;
  } | null>(null);

  const handleFileChosen = (file: File | null, type: 'PHOTO' | 'JSON' | 'PDF' | 'CSV') => {
    if (!file) return;
    setActiveUpload(true);
    setTimeout(() => {
      setActiveUpload(false);
      onUploadReceipt(file.name, type);
    }, 400);
  };

  const handleOpenReview = (job: ReceiptJob) => {
    const store = job.result?.merchant_name || 'Costco Wholesale';
    const updatedLineItems = job.result?.line_items?.map((item) => {
      // Find matching multiplier in table
      const matched =
        multipliers.find(
          (m) =>
            m.store.toLowerCase().includes(store.toLowerCase().slice(0, 6)) &&
            m.item.toLowerCase() === item.name.toLowerCase()
        ) ||
        multipliers.find(
          (m) => m.item.toLowerCase() === item.name.toLowerCase()
        );

      // If matched with a pre-existing stock product, auto-link it!
      if (!item.grocy_product_id && matched?.product_id) {
        return {
          ...item,
          grocy_product_id: matched.product_id,
          grocy_product_name: matched.product_name || item.name,
          unit_multiplier: matched.multiplier ?? 1.0,
          to_create_stock: false,
        };
      }

      const defaultMult = matched?.multiplier ?? item.unit_multiplier ?? 1.0;
      return {
        ...item,
        to_create_stock: item.to_create_stock ?? (!item.grocy_product_id && item.total_price >= 0),
        unit_multiplier: item.unit_multiplier ?? defaultMult,
      };
    });

    setSelectedJobForReview({
      ...job,
      result: job.result
        ? {
            ...job.result,
            line_items: updatedLineItems,
          }
        : undefined,
    });
    setSelectedPeople(['Family']);
    setUpdatePantry(true);
  };

  const handleLinkExistingProduct = (index: number, productId: string) => {
    if (!selectedJobForReview?.result?.line_items) return;
    const prod = products.find((p) => p.id === productId);
    if (!prod) return;
    const items = [...selectedJobForReview.result.line_items];
    items[index] = {
      ...items[index],
      grocy_product_id: prod.id,
      grocy_product_name: prod.name,
      unit_multiplier: prod.unit_multiplier || items[index].unit_multiplier || 1.0,
      to_create_stock: false,
    };
    setSelectedJobForReview({
      ...selectedJobForReview,
      result: { ...selectedJobForReview.result, line_items: items },
    });
  };

  const handleClearProductLink = (index: number) => {
    if (!selectedJobForReview?.result?.line_items) return;
    const items = [...selectedJobForReview.result.line_items];
    items[index] = {
      ...items[index],
      grocy_product_id: undefined,
      grocy_product_name: undefined,
      to_create_stock: true,
      unit_multiplier: 1.0,
    };
    setSelectedJobForReview({
      ...selectedJobForReview,
      result: { ...selectedJobForReview.result, line_items: items },
    });
  };

  const handleToggleCreateStock = (index: number, checked: boolean) => {
    if (!selectedJobForReview?.result?.line_items) return;
    const items = [...selectedJobForReview.result.line_items];
    items[index] = { ...items[index], to_create_stock: checked };
    setSelectedJobForReview({
      ...selectedJobForReview,
      result: { ...selectedJobForReview.result, line_items: items },
    });
  };

  const handleUpdateItemMultiplier = (index: number, multiplier: number) => {
    if (!selectedJobForReview?.result?.line_items) return;
    const items = [...selectedJobForReview.result.line_items];
    items[index] = { ...items[index], unit_multiplier: multiplier };
    setSelectedJobForReview({
      ...selectedJobForReview,
      result: { ...selectedJobForReview.result, line_items: items },
    });
  };

  const handleOpenCreateProduct = (item: ExtractedLineItem, index: number) => {
    setSelectedItemForCreate({ item, index });
    setCreateProductModalOpened(true);
  };

  const handleSaveProductFromModal = (newProd: ProductItem, newConv: ProductUnitConversion) => {
    if (selectedJobForReview?.result?.line_items && selectedItemForCreate) {
      const updatedItems = [...selectedJobForReview.result.line_items];
      updatedItems[selectedItemForCreate.index] = {
        ...updatedItems[selectedItemForCreate.index],
        grocy_product_id: newProd.id,
        grocy_product_name: newProd.name,
        unit_multiplier: newConv.unit_multiplier,
        unit: newConv.stock_unit,
      };
      setSelectedJobForReview({
        ...selectedJobForReview,
        result: {
          ...selectedJobForReview.result,
          line_items: updatedItems,
        },
      });
    }
    if (onCreateProduct) {
      onCreateProduct(newProd, newConv);
    }
    setCreateProductModalOpened(false);
    setSelectedItemForCreate(null);
  };

  const handleConfirm = () => {
    if (selectedJobForReview && onConfirmJob) {
      onConfirmJob(selectedJobForReview, selectedPeople, updatePantry);
      setSelectedJobForReview(null);
    }
  };

  return (
    <Stack gap="md">
      {/* 1. Upload & Camera Dropzone */}
      <Card withBorder radius="md" p="md" bg="blue.0" style={{ borderColor: 'var(--mantine-color-blue-3)' }}>
        <Text fw={800} size="md" c="blue.9" mb={2}>
          Omnichannel CAS Receipt Ingestion
        </Text>
        <Text size="xs" c="dark.3" mb="md">
          Approach 2: Content-Addressable Storage (CAS) with SHA-256 deduplication and async background processing. Review and confirm results before committing to the ledger.
        </Text>

        <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
          <FileButton
            accept="image/*"
            onChange={(file) => handleFileChosen(file, 'PHOTO')}
          >
            {(props) => (
              <Button
                {...props}
                size="sm"
                color="blue"
                leftSection={<IconCamera size={16} />}
                loading={activeUpload}
              >
                Snap Photo
              </Button>
            )}
          </FileButton>

          <FileButton
            accept="application/json,.json"
            onChange={(file) => handleFileChosen(file, 'JSON')}
          >
            {(props) => (
              <Button
                {...props}
                size="sm"
                variant="light"
                color="teal"
                leftSection={<IconFileCode size={16} />}
                loading={activeUpload}
              >
                Import JSON
              </Button>
            )}
          </FileButton>

          <FileButton
            accept="application/pdf,.pdf"
            onChange={(file) => handleFileChosen(file, 'PDF')}
          >
            {(props) => (
              <Button
                {...props}
                size="sm"
                variant="light"
                color="blue"
                leftSection={<IconUpload size={16} />}
                loading={activeUpload}
              >
                Upload PDF
              </Button>
            )}
          </FileButton>

          <FileButton
            accept=".csv,text/csv"
            onChange={(file) => handleFileChosen(file, 'CSV')}
          >
            {(props) => (
              <Button
                {...props}
                size="sm"
                variant="outline"
                color="blue"
                leftSection={<IconReceipt size={16} />}
                loading={activeUpload}
              >
                Import CSV
              </Button>
            )}
          </FileButton>
        </SimpleGrid>
      </Card>

      {/* 2. Ingestion Jobs Feed */}
      <Card withBorder radius="md" p="md">
        <Group justify="space-between" mb="xs">
          <Text fw={700} size="sm">
            Ingestion State Machine ({jobs.length} Jobs)
          </Text>
          <Badge size="xs" color="gray">FastAPI BackgroundTasks</Badge>
        </Group>

        <Stack gap="sm">
          {jobs.map((job) => (
            <Paper key={job.job_id} p="sm" withBorder radius="sm">
              <Group justify="space-between" mb={4}>
                <Group gap="xs">
                  <ThemeIcon
                    color={job.status === 'COMPLETED' ? (job.is_confirmed ? 'teal' : 'blue') : 'blue'}
                    size="sm"
                    radius="xl"
                  >
                    {job.is_confirmed ? <IconCheck size={14} /> : job.status === 'COMPLETED' ? <IconBuildingStore size={14} /> : <IconSparkles size={14} />}
                  </ThemeIcon>
                  <Text size="xs" fw={700}>
                    {job.filename}
                  </Text>
                </Group>
                <Group gap="xs">
                  {job.is_confirmed && (
                    <Badge size="xs" color="teal" variant="filled">
                      ✓ Confirmed
                    </Badge>
                  )}
                  <Badge
                    size="xs"
                    color={job.status === 'COMPLETED' ? 'teal' : 'indigo'}
                    variant="light"
                  >
                    {job.status}
                  </Badge>
                </Group>
              </Group>

              <Text size="11px" c="dimmed" mb={4}>
                SHA-256: <code>{job.file_hash}</code>
              </Text>

              <Progress
                value={job.progress_pct}
                color={job.status === 'COMPLETED' ? (job.is_confirmed ? 'teal' : 'blue') : 'indigo'}
                size="xs"
                animated={job.status === 'PROCESSING'}
              />

              <Group justify="space-between" mt={4}>
                <Text size="11px" c="dark.3">
                  {job.progress_message}
                </Text>
                {job.result && (
                  <Text size="11px" fw={600} c="teal.8">
                    ${job.result.total_amount.toFixed(2)} • {job.result.line_items_count} items
                  </Text>
                )}
              </Group>

              {/* Action Buttons for Completed Jobs */}
              {job.status === 'COMPLETED' && (
                <Group justify="flex-end" mt={8}>
                  {job.is_confirmed ? (
                    <Badge color="teal" variant="light" size="sm" leftSection={<IconCheck size={12} />}>
                      Event Logged to Ledger
                    </Badge>
                  ) : (
                    <Button
                      size="xs"
                      variant="filled"
                      color="teal"
                      leftSection={<IconCheck size={14} />}
                      onClick={() => handleOpenReview(job)}
                    >
                      Check & Confirm
                    </Button>
                  )}
                </Group>
              )}
            </Paper>
          ))}
        </Stack>
      </Card>

      {/* 3. Unified Event Modal for Shopping Receipt */}
      <EventModal
        opened={!!selectedJobForReview}
        event={null}
        receiptJob={selectedJobForReview}
        products={products}
        multipliers={multipliers}
        onClose={() => setSelectedJobForReview(null)}
        onConfirmReceiptJob={(job, people, updatePantry, lineItems) => {
          if (onConfirmJob) {
            onConfirmJob(
              {
                ...job,
                result: job.result
                  ? {
                      ...job.result,
                      line_items: lineItems || job.result.line_items,
                    }
                  : undefined,
              },
              people,
              updatePantry
            );
          }
          setSelectedJobForReview(null);
        }}
        onUpsertMultiplier={onUpsertMultiplier}
      />

      {/* 4. Create Product & Multiplier Mapping Modal */}
      <CreateProductModal
        opened={createProductModalOpened}
        onClose={() => {
          setCreateProductModalOpened(false);
          setSelectedItemForCreate(null);
        }}
        onSave={handleSaveProductFromModal}
        initialData={
          selectedItemForCreate
            ? {
                name: selectedItemForCreate.item.name,
                store_name: selectedJobForReview?.result?.merchant_name || 'Costco Wholesale',
                purchase_unit: selectedItemForCreate.item.unit || 'pack',
                unit_price: selectedItemForCreate.item.unit_price,
                receipt_quantity: selectedItemForCreate.item.quantity,
              }
            : undefined
        }
      />
    </Stack>
  );
};
