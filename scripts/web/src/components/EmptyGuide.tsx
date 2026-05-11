import { Empty, Button } from 'antd';

interface EmptyGuideProps {
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function EmptyGuide({ description, actionLabel, onAction }: EmptyGuideProps) {
  return (
    <div className="empty-state">
      <Empty description={description}>
        {actionLabel && onAction && (
          <Button type="primary" onClick={onAction}>{actionLabel}</Button>
        )}
      </Empty>
    </div>
  );
}
