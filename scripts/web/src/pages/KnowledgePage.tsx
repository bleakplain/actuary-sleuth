import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, Table, Button, Space, Modal, Typography, message, Progress, Statistic, Row, Col, Popconfirm, Descriptions, Tag, Spin } from 'antd';
import { DatabaseOutlined, ReloadOutlined, ImportOutlined, SyncOutlined, UnorderedListOutlined } from '@ant-design/icons';
import * as kbApi from '../api/knowledge';
import type { Document, IndexStatus } from '../types';

const { Title, Text } = Typography;

interface ChunkItem {
  law_name: string;
  article_number: string;
  category: string;
  hierarchy_path: string;
  source_file: string;
  doc_number: string;
  issuing_authority: string;
  effective_date: string;
  text: string;
  text_length: number;
}

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>('');

  // 分块查看状态
  const [chunksOpen, setChunksOpen] = useState(false);
  const [chunksDocName, setChunksDocName] = useState('');
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [selectedChunk, setSelectedChunk] = useState<ChunkItem | null>(null);
  const [sourceContent, setSourceContent] = useState('');
  const [chunksLoading, setChunksLoading] = useState(false);
  const [highlightPos, setHighlightPos] = useState<{ start: number; end: number } | null>(null);
  const [highlightKey, setHighlightKey] = useState(0);
  const sourceRef = useRef<HTMLPreElement>(null);

  // highlightPos 变化时执行高亮；highlightKey 变化时强制 pre 重新渲染以清除旧高亮
  useEffect(() => {
    const node = sourceRef.current;
    if (!node || highlightPos === null) return;
    // 等待 DOM 更新
    requestAnimationFrame(() => {
      const pre = sourceRef.current;
      if (!pre) return;
      const textNode = pre.childNodes[0];
      if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return;
      const range = document.createRange();
      range.setStart(textNode, highlightPos.start);
      range.setEnd(textNode, highlightPos.end);
      const mark = document.createElement('mark');
      mark.style.background = '#fff3cd';
      range.surroundContents(mark);
      mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [highlightPos, highlightKey]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, status] = await Promise.all([kbApi.fetchDocuments(), kbApi.fetchIndexStatus()]);
      setDocuments(docs);
      setIndexStatus(status);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!taskId || taskStatus === 'completed' || taskStatus === 'failed') return;
    const timer = setInterval(async () => {
      try {
        const task = await kbApi.fetchTaskStatus(taskId);
        setTaskStatus(task.status);
        if (task.status === 'completed' || task.status === 'failed') {
          clearInterval(timer);
          if (task.status === 'completed') {
            message.success('操作完成');
            loadData();
          } else {
            message.error(`操作失败: ${task.progress}`);
          }
        }
      } catch {
        clearInterval(timer);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [taskId, taskStatus, loadData]);

  const handleImport = async () => {
    try {
      const { task_id } = await kbApi.importDocuments('*.md');
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始导入...');
    } catch (err) {
      message.error(`导入失败: ${err}`);
    }
  };

  const handleRebuild = async () => {
    try {
      const { task_id } = await kbApi.rebuildIndex('*.md', true);
      setTaskId(task_id);
      setTaskStatus('pending');
      message.info('开始重建索引...');
    } catch (err) {
      message.error(`重建失败: ${err}`);
    }
  };

  const locateInSource = useCallback((text: string) => {
    // 提取具体条款文本：找到"第X条"开头，截取到下一个"第X条"或章节标题之前
    const articleMatch = text.match(/第[一二三四五六七八九十百千\d]+条[\s\S]*?/) || [text];
    const articleText = articleMatch[0].slice(0, 500);
    const snippet = articleText.replace(/\s+/g, '').slice(0, 80);
    const cleanSource = sourceContent.replace(/\s+/g, '');
    const idx = cleanSource.indexOf(snippet);
    if (idx >= 0) {
      // 映射回原始文本位置
      let srcIdx = 0, cleanIdx = 0;
      while (cleanIdx < idx && srcIdx < sourceContent.length) {
        if (!/\s/.test(sourceContent[srcIdx])) cleanIdx++;
        srcIdx++;
      }
      // 找到这一条的结束位置（下一个"第X条"或章节标题）
      const endSnippet = articleText.replace(/\s+/g, '');
      let endSrc = srcIdx, endClean = cleanIdx;
      while (endClean < cleanIdx + endSnippet.length && endSrc < sourceContent.length) {
        if (!/\s/.test(sourceContent[endSrc])) endClean++;
        endSrc++;
      }
      // 在原始文本中找到下一个"第X条"作为结束边界
      const afterPos = sourceContent.indexOf('\n', srcIdx);
      if (afterPos > 0) {
        const rest = sourceContent.slice(afterPos);
        const nextArticle = rest.search(/\n[第（][一二三四五六七八九十百千\d]+[条）]/);
        if (nextArticle > 0) {
          endSrc = afterPos + nextArticle;
        }
      }
      setHighlightPos({ start: srcIdx, end: endSrc });
    }
  }, [sourceContent]);

  const handleViewChunks = async (name: string) => {
    setChunksLoading(true);
    setChunksOpen(true);
    setChunksDocName(name);
    setSelectedChunk(null);
    setHighlightPos(null);
    setHighlightKey(k => k + 1);
    try {
      const [previewResult, chunksResult] = await Promise.all([
        kbApi.fetchDocumentPreview(name),
        kbApi.fetchDocumentChunks(name),
      ]);
      setSourceContent(previewResult.content);
      setChunks(chunksResult.chunks as ChunkItem[]);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setChunksLoading(false);
    }
  };

  const columns = [
    { title: '文档名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '条款数',
      dataIndex: 'clause_count',
      key: 'clause_count',
      width: 100,
      sorter: (a: Document, b: Document) => a.clause_count - b.clause_count,
    },
    {
      title: '文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (size: number) => (size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`),
      sorter: (a: Document, b: Document) => a.file_size - b.file_size,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: string, record: Document) => (
        <Button type="link" icon={<UnorderedListOutlined />} onClick={() => handleViewChunks(record.name)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>知识库管理</Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="文档数量" value={documents.length} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="向量库文档" value={indexStatus?.document_count || 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="BM25 状态"
              value={indexStatus?.bm25?.loaded ? '已加载' : '未加载'}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="向量库状态"
              value={indexStatus?.vector_db?.status || '未知'}
            />
          </Card>
        </Col>
      </Row>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<ImportOutlined />}
          onClick={handleImport}
          loading={taskStatus === 'running' || taskStatus === 'pending'}
        >
          导入文档
        </Button>
        <Popconfirm
          title="确定重建索引？此操作会重新处理所有文档。"
          onConfirm={handleRebuild}
        >
          <Button
            icon={<SyncOutlined />}
            loading={taskStatus === 'running' || taskStatus === 'pending'}
          >
            重建索引
          </Button>
        </Popconfirm>
        <Button icon={<ReloadOutlined />} onClick={loadData}>
          刷新
        </Button>
      </Space>

      {(taskStatus === 'pending' || taskStatus === 'running') && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Progress percent={taskStatus === 'pending' ? 0 : 50} status="active" />
          <Text type="secondary">
            {taskStatus === 'pending' ? '等待中...' : '处理中...'}
          </Text>
        </Card>
      )}

      <Card>
        <Table
          dataSource={documents}
          columns={columns}
          rowKey="name"
          loading={loading}
          pagination={{ pageSize: 20 }}
          size="middle"
        />
      </Card>

      <Modal
        title={`分块验证 — ${chunksDocName} (${chunks.length} 块)`}
        open={chunksOpen}
        onCancel={() => { setChunksOpen(false); setSelectedChunk(null); }}
        footer={null}
        width="95vw"
        style={{ top: 20, maxWidth: 1600 }}
        bodyStyle={{ padding: 0, height: 'calc(100vh - 120px)' }}
      >
        {chunksLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" tip="加载中..." /></div>
        ) : (
          <Row style={{ height: '100%' }}>
            {/* 左栏：md 原文 */}
            <Col
              span={10}
              style={{
                height: '100%',
                borderRight: '1px solid #f0f0f0',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <div style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
                原文 ({chunksDocName})
              </div>
              <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
                <pre key={highlightKey} ref={sourceRef} style={{ margin: 0, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                  {sourceContent}
                </pre>
              </div>
            </Col>

            {/* 右栏：提取的条款列表 */}
            <Col
              span={14}
              style={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <div style={{ padding: '8px 12px', fontWeight: 600, borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
                提取条款 ({chunks.length})
              </div>
              {selectedChunk ? (
                <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
                  <Button
                    size="small"
                    style={{ marginBottom: 12 }}
                    onClick={() => { setSelectedChunk(null); setHighlightPos(null); setHighlightKey(k => k + 1); }}
                  >
                    &larr; 返回列表
                  </Button>
                  <Descriptions size="small" bordered column={1} style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="法规名称">{selectedChunk.law_name}</Descriptions.Item>
                    <Descriptions.Item label="条款号">{selectedChunk.article_number}</Descriptions.Item>
                    <Descriptions.Item label="分类">
                      <Tag>{selectedChunk.category}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="层级路径">{selectedChunk.hierarchy_path}</Descriptions.Item>
                    <Descriptions.Item label="来源文件">{selectedChunk.source_file}</Descriptions.Item>
                    {selectedChunk.doc_number && (
                      <Descriptions.Item label="发文号">{selectedChunk.doc_number}</Descriptions.Item>
                    )}
                    {selectedChunk.issuing_authority && (
                      <Descriptions.Item label="发文机关">{selectedChunk.issuing_authority}</Descriptions.Item>
                    )}
                    {selectedChunk.effective_date && (
                      <Descriptions.Item label="生效日期">{selectedChunk.effective_date}</Descriptions.Item>
                    )}
                    <Descriptions.Item label="字数">{selectedChunk.text_length}</Descriptions.Item>
                  </Descriptions>
                  <div
                    style={{
                      background: '#fafafa',
                      padding: 12,
                      borderRadius: 6,
                      fontSize: 13,
                      lineHeight: 1.8,
                      whiteSpace: 'pre-wrap',
                      maxHeight: 'calc(100vh - 400px)',
                      overflow: 'auto',
                    }}
                  >
                    {selectedChunk.text}
                  </div>
                </div>
              ) : (
                <div style={{ flex: 1, overflow: 'auto' }}>
                  <Table
                    dataSource={chunks}
                    rowKey={(_, i) => String(i)}
                    size="small"
                    pagination={false}
                    onRow={(record) => ({
                      onClick: () => {
                        setSelectedChunk(record);
                        locateInSource(record.text);
                      },
                      style: { cursor: 'pointer' },
                    })}
                    columns={[
                      {
                        title: '#',
                        key: 'idx',
                        width: 40,
                        render: (_: unknown, __: unknown, i: number) => i + 1,
                      },
                      {
                        title: '条款号',
                        dataIndex: 'article_number',
                        key: 'article_number',
                        width: 200,
                        ellipsis: true,
                        render: (v: string) => v === '未知' ? <Text type="secondary">{v}</Text> : v,
                      },
                      {
                        title: '分类',
                        dataIndex: 'category',
                        key: 'category',
                        width: 90,
                        render: (v: string) => <Tag>{v}</Tag>,
                      },
                      {
                        title: '字数',
                        dataIndex: 'text_length',
                        key: 'text_length',
                        width: 60,
                      },
                      {
                        title: '内容摘要',
                        key: 'preview',
                        render: (_: unknown, r: ChunkItem) => (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {r.text.slice(0, 80)}...
                          </Text>
                        ),
                      },
                    ]}
                  />
                </div>
              )}
            </Col>
          </Row>
        )}
      </Modal>
    </div>
  );
}
