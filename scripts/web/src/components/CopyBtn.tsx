import { useState, useCallback } from 'react';
import { CopyOutlined } from '@ant-design/icons';

export default function CopyBtn({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;left:-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // fallback to clipboard API
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    } finally {
      document.body.removeChild(ta);
    }
  }, [text]);

  return (
    <CopyOutlined
      style={{ fontSize: 11, color: '#d9d9d9', cursor: 'pointer', marginLeft: 4 }}
      onClick={handleCopy}
      title={copied ? '已复制' : '复制'}
    />
  );
}
