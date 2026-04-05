import { useState } from 'react';
import { Modal, DatePicker, Select, Button, Space, Typography, message } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { cleanupTraces } from '../../api/observability';
import type { CleanupResponse } from '../../types';
import dayjs, { Dayjs } from 'dayjs';

interface Props {
  open: boolean;
  onClose: () => void;
  onCleanupDone: () => void;
}

export default function CleanupDialog({ open, onClose, onCleanupDone }: Props) {
  const [startDate, setStartDate] = useState<Dayjs | null>(null);
  const [endDate, setEndDate] = useState<Dayjs | null>(null);
  const [status, setStatus] = useState<string>('');
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const handlePreview = async () => {
    setLoading(true);
    try {
      const result: CleanupResponse = await cleanupTraces({
        start_date: startDate?.format('YYYY-MM-DD') || '',
        end_date: endDate?.format('YYYY-MM-DD') || '',
        status,
        preview: true,
      });
      setPreviewCount(result.count ?? 0);
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async () => {
    setLoading(true);
    try {
      const result: CleanupResponse = await cleanupTraces({
        start_date: startDate?.format('YYYY-MM-DD') || '',
        end_date: endDate?.format('YYYY-MM-DD') || '',
        status,
        preview: false,
      });
      message.success(`已清理 ${result.deleted} 条 trace`);
      onCleanupDone();
      handleClose();
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setStartDate(null);
    setEndDate(null);
    setStatus('');
    setPreviewCount(null);
    onClose();
  };

  return (
    <Modal
      title="批量清理 Trace"
      open={open}
      onCancel={handleClose}
      footer={null}
      width={440}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <div style={{ marginBottom: 4, fontSize: 13, color: '#595959' }}>时间范围</div>
          <DatePicker.RangePicker
            value={[startDate, endDate]}
            onChange={(dates) => {
              setStartDate(dates?.[0] ?? null);
              setEndDate(dates?.[1] ?? null);
            }}
            style={{ width: '100%' }}
          />
        </div>
        <div>
          <div style={{ marginBottom: 4, fontSize: 13, color: '#595959' }}>状态</div>
          <Select
            value={status || undefined}
            onChange={setStatus}
            placeholder="全部"
            allowClear
            style={{ width: '100%' }}
            options={[
              { label: '全部', value: '' },
              { label: '成功 (ok)', value: 'ok' },
              { label: '错误 (error)', value: 'error' },
            ]}
          />
        </div>

        <Button onClick={handlePreview} loading={loading} block>
          预览影响数量
        </Button>

        {previewCount !== null && (
          <div style={{
            padding: '8px 12px', background: previewCount > 0 ? '#fff7e6' : '#f6ffed',
            borderRadius: 6, fontSize: 13,
          }}>
            <Typography.Text type={previewCount > 0 ? 'warning' : 'success'}>
              {previewCount > 0
                ? `将清理 ${previewCount} 条 trace 及其 span 数据`
                : '没有符合条件的 trace'}
            </Typography.Text>
          </div>
        )}

        {previewCount !== null && previewCount > 0 && (
          <Button
            type="primary"
            danger
            icon={<DeleteOutlined />}
            onClick={handleExecute}
            loading={loading}
            block
          >
            确认清理
          </Button>
        )}
      </Space>
    </Modal>
  );
}
