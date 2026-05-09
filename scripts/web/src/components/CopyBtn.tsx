import { useState, useCallback } from 'react';
import { CopyOutlined } from '@ant-design/icons';
import { theme } from 'antd';

export default function CopyBtn({ text }: { text: string }) {
  const { token } = theme.useToken();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0;left:-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      aria-label={copied ? '已复制' : '复制'}
      style={{ fontSize: 11, color: token.colorBorder, cursor: 'pointer', marginLeft: 4, background: 'none', border: 'none', padding: 0 }}
    >
      <CopyOutlined />
    </button>
  );
}
