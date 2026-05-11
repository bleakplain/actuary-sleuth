import { Typography } from 'antd';

const { Title, Text } = Typography;

interface PageHeaderProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  extra?: React.ReactNode;
  isMobile?: boolean;
}

export default function PageHeader({ icon, title, description, extra, isMobile }: PageHeaderProps) {
  return (
    <div className="flex-between" style={{ marginBottom: 16 }}>
      <div>
        <Title level={4} style={{ margin: 0 }}>
          {icon}{icon ? <span style={{ marginLeft: 8 }}>{title}</span> : title}
        </Title>
        {!isMobile && description && (
          <Text type="secondary" style={{ fontSize: 13, marginTop: 2, display: 'block' }}>
            {description}
          </Text>
        )}
      </div>
      {extra}
    </div>
  );
}
