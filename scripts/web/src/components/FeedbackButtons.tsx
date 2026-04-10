import { useState } from 'react';
import { Button, Select, Input, Space, message, theme } from 'antd';
import { LikeOutlined, DislikeOutlined } from '@ant-design/icons';
import * as feedbackApi from '../api/feedback';

const REASON_OPTIONS = [
  { label: '答案错误', value: '答案错误' },
  { label: '没有回答我的问题', value: '没有回答我的问题' },
  { label: '回答不完整', value: '回答不完整' },
  { label: '引用不准确', value: '引用不准确' },
  { label: '信息过时', value: '信息过时' },
  { label: '其他', value: '其他' },
];

interface Props {
  messageId: number;
  existingFeedback?: 'up' | 'down';
}

export default function FeedbackButtons({ messageId, existingFeedback }: Props) {
  const { token } = theme.useToken();
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(existingFeedback || null);
  const [showReason, setShowReason] = useState(false);
  const [reason, setReason] = useState('');
  const [correction, setCorrection] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (rating: 'up' | 'down') => {
    setSubmitting(true);
    try {
      await feedbackApi.submitFeedback({
        message_id: messageId,
        rating,
        reason: rating === 'down' ? reason : '',
        correction: rating === 'down' ? correction : '',
      });
      message.success('感谢反馈');
      setFeedback(rating);
      setShowReason(false);
    } catch {
      message.error('反馈提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpClick = () => {
    handleSubmit('up');
  };

  const handleDownClick = () => {
    setFeedback('down');
    setShowReason(true);
  };

  if (feedback === 'up' && !showReason) {
    return (
      <Button type="text" size="small" icon={<LikeOutlined />} style={{ color: token.colorSuccess }}>
        已标记有用
      </Button>
    );
  }

  return (
    <>
      <Space size={4}>
        <Button
          type="text"
          size="small"
          icon={<LikeOutlined />}
          onClick={handleUpClick}
          disabled={submitting}
          style={{ color: feedback === 'up' ? token.colorSuccess : undefined }}
        >
          有用
        </Button>
        <Button
          type="text"
          size="small"
          icon={<DislikeOutlined />}
          onClick={handleDownClick}
          disabled={submitting}
          style={{ color: feedback === 'down' ? token.colorError : undefined }}
        >
          有问题
        </Button>
      </Space>
      {showReason && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Select
            placeholder="选择原因"
            options={REASON_OPTIONS}
            value={reason || undefined}
            onChange={setReason}
            style={{ width: '100%' }}
            size="small"
          />
          <Input.TextArea
            placeholder="可选：提供正确答案"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            rows={2}
            size="small"
          />
          <Space>
            <Button size="small" type="primary" onClick={() => handleSubmit('down')} loading={submitting}>
              提交
            </Button>
            <Button size="small" onClick={() => { setShowReason(false); setFeedback(null); }}>
              取消
            </Button>
          </Space>
        </div>
      )}
    </>
  );
}
