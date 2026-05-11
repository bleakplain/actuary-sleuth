import { useState, useEffect, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import mammoth from 'mammoth';
import DOMPurify from 'dompurify';
import { Skeleton, Alert } from 'antd';

pdfjs.GlobalWorkerOptions.workerSrc = pdfjsWorker;

interface DocumentViewerProps {
  file: File | null;
  fileType: string;
}

export function DocumentViewer({ file, fileType }: DocumentViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [docxHtml, setDocxHtml] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string>('');

  const scale = 1.2;

  // PDF 文件数据 - 直接传递 File 对象给 react-pdf
  // react-pdf 会内部处理，无需手动创建 Blob URL

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
        // 使用 DOMPurify 消毒 HTML，防止 XSS
        const sanitizedHtml = DOMPurify.sanitize(result.value);
        setDocxHtml(sanitizedHtml);
        setLoading(false);
      } catch (err: unknown) {
        setError(`DOCX 解析失败: ${err instanceof Error ? err.message : String(err)}`);
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
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (error) {
    return <Alert type="error" message={error} />;
  }

  // PDF 查看 - 显示所有页面
  if (fileType === '.pdf' && file) {
    return (
      <div style={{ height: '100%', overflow: 'auto' }}>
        <Document
          file={file}
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