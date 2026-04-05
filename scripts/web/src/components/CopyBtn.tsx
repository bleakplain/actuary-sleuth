import { useState } from 'react';
import { CopyOutlined } from '@ant-design/icons';

export default function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <CopyOutlined
      style={{ fontSize: 11, color: '#d9d9d9', cursor: 'pointer', marginLeft: 4 }}
      onClick={(e) => { e.stopPropagation(); handleCopy(); }}
      title={copied ? '已复制' : '复制'}
    />
  );
}
