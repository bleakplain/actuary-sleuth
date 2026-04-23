import { useState, useEffect, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import mammoth from 'mammoth';
import { Spin, Alert } from 'antd';

// 设置 PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface DocumentViewerProps {
  file: File | null;
  fileType: string;
  highlightPage?: number;
  highlightBbox?: [number, number, number, number];
}

export function DocumentViewer({ file, fileType }: DocumentViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [docxHtml, setDocxHtml] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const scale = 1.2;

  // 处理 DOCX 文件
  useEffect(() => {
    if (!file || fileType !== '.docx') return;
    setLoading(true);
    setError('');
    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const arrayBuffer = e.target?.result as ArrayBuffer;
        const result = await mammoth.convertToHtml({ arrayBuffer });
        setDocxHtml(result.value);
        setLoading(false);
      } catch (err) {
        setError(`DOCX 解析失败: ${err}`);
        setLoading(false);
      }
    };
    reader.onerror = () => {
      setError('文件读取失败');
      setLoading(false);
    };
    reader.readAsArrayBuffer(file);
  }, [file, fileType]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setLoading(false);
  }, []);

  if (!file) {
    return <Alert type="info" message="请上传文档" />;
  }

  if (loading) {
    return <Spin tip="加载文档..." />;
  }

  if (error) {
    return <Alert type="error" message={error} />;
  }

  // PDF 查看 - 显示所有页面
  if (fileType === '.pdf') {
    const fileUrl = URL.createObjectURL(file);
    return (
      <div style={{ height: '100%', overflow: 'auto' }}>
        <Document
          file={fileUrl}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={(err) => setError(`PDF 加载失败: ${err}`)}
        >
          {Array.from(new Array(numPages), (_, index) => (
            <Page key={`page_${index + 1}`} pageNumber={index + 1} scale={scale} />
          ))}
        </Document>
      </div>
    );
  }

  // DOCX 查看
  if (fileType === '.docx') {
    return (
      <div style={{ height: '100%', overflow: 'auto', padding: '16px' }}>
        <div
          style={{
            fontFamily: 'serif',
            lineHeight: 1.6,
            maxWidth: '800px',
          }}
          dangerouslySetInnerHTML={{ __html: docxHtml }}
        />
      </div>
    );
  }

  return <Alert type="warning" message={`不支持 ${fileType} 格式`} />;
}