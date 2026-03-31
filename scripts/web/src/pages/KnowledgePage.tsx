import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, Table, Button, Space, Modal, Typography, message, Progress, Statistic, Row, Col, Popconfirm, Descriptions, Tag, Spin, Drawer, Input, Badge } from 'antd';
import { DatabaseOutlined, ReloadOutlined, ImportOutlined, PlusOutlined, UnorderedListOutlined, HistoryOutlined, DeleteOutlined, CheckCircleOutlined } from '@ant-design/icons';
import * as kbApi from '../api/knowledge';
import type { KBVersion } from '../api/knowledge';
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
  const [highlightLines, setHighlightLines] = useState<{ start: number; end: number } | null>(null);
  const sourceRef = useRef<HTMLDivElement>(null);

  // 版本管理状态
  const [versions, setVersions] = useState<KBVersion[]>([]);
  const [activeVersion, setActiveVersion] = useState('');
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [createVersionModalOpen, setCreateVersionModalOpen] = useState(false);
  const [versionDescription, setVersionDescription] = useState('');

  // highlightLines 变化时滚动到高亮行
  useEffect(() => {
    if (!highlightLines || !sourceRef.current) return;
    requestAnimationFrame(() => {
      const el = sourceRef.current?.querySelector('[data-highlight]');
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [highlightLines]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, status, verData] = await Promise.all([
        kbApi.fetchDocuments(),
        kbApi.fetchIndexStatus(),
        kbApi.fetchVersions(),
      ]);
      setDocuments(docs);
      setIndexStatus(status);
      setVersions(verData.versions);
      setActiveVersion(verData.active_version);
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

  const handleCreateVersion = async () => {
    try {
      const { task_id } = await kbApi.createVersion(versionDescription || undefined);
      setTaskId(task_id);
      setTaskStatus('pending');
      setCreateVersionModalOpen(false);
      setVersionDescription('');
      message.info('开始创建新版本...');
    } catch (err) {
      message.error(`创建版本失败: ${err}`);
    }
  };

  const handleActivateVersion = async (versionId: string) => {
    try {
      await kbApi.activateVersion(versionId);
      message.success(`已切换到 ${versionId}`);
      loadData();
    } catch (err) {
      message.error(`切换失败: ${err}`);
    }
  };

  const handleDeleteVersion = async (versionId: string) => {
    try {
      await kbApi.deleteVersion(versionId);
      message.success(`已删除 ${versionId}`);
      loadData();
    } catch (err) {
      message.error(`删除失败: ${err}`);
    }
  };

  const locateInSource = useCallback((text: string) => {
    // 在原文中按行查找条款位置
    const articleMatch = text.match(/第[一二三四五六七八九十百千\d]+条[\s\S]*?/) || [text];
    const articleText = articleMatch[0].slice(0, 500);
    const snippet = articleText.replace(/\s+/g, '').slice(0, 80);
    const lines = sourceContent.split('\n');

    // 逐行匹配：去除空白后比较前80字符
    let startLine = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].replace(/\s+/g, '').startsWith(snippet)) {
        startLine = i;
        break;
      }
    }
    if (startLine < 0) return;

    // 从起始行往下找下一个"第X条"作为结束行
    let endLine = lines.length;
    for (let i = startLine + 1; i < lines.length; i++) {
      if (/^\s*[第（][一二三四五六七八九十百千\d]+[条）]/.test(lines[i])) {
        endLine = i;
        break;
      }
    }
    setHighlightLines({ start: startLine, end: endLine });
  }, [sourceContent]);

  const handleViewChunks = async (name: string) => {
    setChunksLoading(true);
    setChunksOpen(true);
    setChunksDocName(name);
    setSelectedChunk(null);
    setHighlightLines(null);
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
              title="当前版本"
              value={activeVersion || '-'}
              suffix={activeVersion && <Tag color="blue" style={{ marginLeft: 4 }}>{versions.find(v => v.version_id === activeVersion)?.description || '当前激活'}</Tag>}
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
        <Button
          icon={<PlusOutlined />}
          onClick={() => setCreateVersionModalOpen(true)}
          loading={taskStatus === 'running' || taskStatus === 'pending'}
        >
          创建新版本
        </Button>
        <Button icon={<HistoryOutlined />} onClick={() => setVersionDrawerOpen(true)}>
          版本管理
        </Button>
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
                <div ref={sourceRef} style={{ margin: 0, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                  {sourceContent.split('\n').map((line, i) => {
                    const isHighlighted = highlightLines && i >= highlightLines.start && i < highlightLines.end;
                    return (
                      <div
                        key={i}
                        data-highlight={isHighlighted ? 'true' : undefined}
                        style={{
                          background: isHighlighted ? '#fff3cd' : undefined,
                          padding: isHighlighted ? '0 2px' : undefined,
                          borderRadius: 2,
                        }}
                      >
                        {line || '\u00A0'}
                      </div>
                    );
                  })}
                </div>
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
                    onClick={() => { setSelectedChunk(null); setHighlightLines(null); }}
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

      <Modal
        title="创建新版本"
        open={createVersionModalOpen}
        onOk={handleCreateVersion}
        onCancel={() => { setCreateVersionModalOpen(false); setVersionDescription(''); }}
        okText="创建"
        cancelText="取消"
      >
        <p style={{ color: '#666', marginBottom: 12 }}>
          将从当前工作目录的源文件创建快照，并重建索引。创建完成后自动切换到新版本。
        </p>
        <Input.TextArea
          placeholder="版本描述（可选，如：优化分块策略）"
          value={versionDescription}
          onChange={e => setVersionDescription(e.target.value)}
          rows={2}
        />
      </Modal>

      <Drawer
        title="版本管理"
        open={versionDrawerOpen}
        onClose={() => setVersionDrawerOpen(false)}
        width={600}
      >
        <Table
          dataSource={versions}
          rowKey="version_id"
          pagination={false}
          size="small"
          rowClassName={record => record.active ? 'ant-table-row-active' : ''}
          columns={[
            {
              title: '版本',
              dataIndex: 'version_id',
              key: 'version_id',
              width: 70,
              render: (v: string, r: KBVersion) => (
                <Space>
                  <Tag color={r.active ? 'blue' : 'default'}>{v}</Tag>
                  {r.active && <Badge status="processing" />}
                </Space>
              ),
            },
            {
              title: '描述',
              dataIndex: 'description',
              key: 'description',
              ellipsis: true,
              render: (v: string) => v || '-',
            },
            {
              title: '文档',
              dataIndex: 'document_count',
              key: 'document_count',
              width: 60,
            },
            {
              title: '分块',
              dataIndex: 'chunk_count',
              key: 'chunk_count',
              width: 60,
            },
            {
              title: '创建时间',
              dataIndex: 'created_at',
              key: 'created_at',
              width: 160,
              ellipsis: true,
            },
            {
              title: '操作',
              key: 'action',
              width: 120,
              render: (_: unknown, record: KBVersion) => (
                <Space size="small">
                  {!record.active && (
                    <Popconfirm
                      title={`切换到 ${record.version_id}？`}
                      onConfirm={() => handleActivateVersion(record.version_id)}
                    >
                      <Button type="link" size="small" icon={<CheckCircleOutlined />}>激活</Button>
                    </Popconfirm>
                  )}
                  {!record.active && (
                    <Popconfirm
                      title={`确定删除 ${record.version_id}？此操作不可恢复。`}
                      onConfirm={() => handleDeleteVersion(record.version_id)}
                    >
                      <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
