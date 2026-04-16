import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Card, Table, Button, Space, Modal, Typography, message, Progress, Statistic, Row, Col, Popconfirm, Descriptions, Tag, Spin, Drawer, Input, Badge, Tree, Tabs, theme, Grid } from 'antd';
import { DatabaseOutlined, ReloadOutlined, ImportOutlined, PlusOutlined, UnorderedListOutlined, HistoryOutlined, DeleteOutlined, CheckCircleOutlined, FolderOutlined, FileOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import * as kbApi from '../api/knowledge';
import type { KBVersion } from '../api/knowledge';
import type { Document, IndexStatus } from '../types';
import { DRAWER_MD, MODAL_SM } from '../constants/layout';

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
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [documents, setDocuments] = useState<Document[]>([]);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<string>('');
  const [taskProgress, setTaskProgress] = useState<string>('');

  // 分块查看状态
  const [chunksOpen, setChunksOpen] = useState(false);
  const [chunksFilePath, setChunksFilePath] = useState('');
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [selectedChunk, setSelectedChunk] = useState<ChunkItem | null>(null);
  const [rawContent, setRawContent] = useState('');

  // 派生状态
  const chunksDocName = chunksFilePath.split('/').pop() || chunksFilePath;
  const sourceContent = useMemo(() => rawContent
    .replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '')
    .replace(/^>\s*\*\*元数据\*\*.*$/gm, ''), [rawContent]);

  const [chunksLoading, setChunksLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [highlightLines, setHighlightLines] = useState<{ start: number; end: number } | null>(null);
  const sourceRef = useRef<HTMLDivElement>(null);

  // 版本管理状态
  const [versions, setVersions] = useState<KBVersion[]>([]);
  const [activeVersion, setActiveVersion] = useState('');
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [createVersionModalOpen, setCreateVersionModalOpen] = useState(false);
  const [versionDescription, setVersionDescription] = useState('');

  // highlightLines 变化时在 ReactMarkdown DOM 中高亮对应段落并滚动
  useEffect(() => {
    const container = sourceRef.current;
    if (!container) return;

    // 清除旧高亮
    container.querySelectorAll('.kb-highlight').forEach(el => el.classList.remove('kb-highlight'));

    if (!highlightLines) return;

    const lines = sourceContent.split('\n');
    // 提取高亮区域的文本（去除空白后用于匹配）
    const hlText = lines
      .slice(highlightLines.start - 1, highlightLines.end)
      .join('')
      .replace(/\s+/g, '')
      .slice(0, 200);

    if (!hlText) return;

    requestAnimationFrame(() => {
      // 遍历 ReactMarkdown 渲染的所有块级元素，检查文本内容是否匹配
      const blocks = container.querySelectorAll('p, li, h1, h2, h3, h4, h5, h6, blockquote, pre, tr');
      for (const block of blocks) {
        const text = block.textContent?.replace(/\s+/g, '') || '';
        if (text.length > 10 && hlText.includes(text.slice(0, Math.min(text.length, 60)))) {
          block.classList.add('kb-highlight');
        }
      }

      // 滚动到第一个高亮元素
      const first = container.querySelector('.kb-highlight');
      first?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }, [highlightLines, sourceContent]);

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
    } catch (err: any) {
      console.error('KnowledgePage loadData error:', err);
      message.error(`加载失败: ${err?.message || err}`);
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
        setTaskProgress(task.progress);
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
      setTaskProgress('');
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
      setTaskProgress('');
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
    const lines = sourceContent.split('\n');
    const flatSource = sourceContent.replace(/\s+/g, '');
    const snippet = text.replace(/\s+/g, '').slice(0, 80);

    // 在去空白的全文中定位 snippet
    const pos = flatSource.indexOf(snippet);
    if (pos < 0) return;

    // 反算对应的源码行号
    let charCount = 0;
    let startLine = -1;
    for (let i = 0; i < lines.length; i++) {
      const lineLen = lines[i].replace(/\s+/g, '').length;
      if (charCount + lineLen > pos) {
        startLine = i;
        break;
      }
      charCount += lineLen;
    }
    if (startLine < 0) return;

    // 从起始行往上找标题行（## 第N项 或 第X条）
    let headerLine = startLine;
    for (let i = startLine; i >= 0; i--) {
      if (/^##\s*第\d+项/.test(lines[i]) || /^\s*第[一二三四五六七八九十百千\d]+条/.test(lines[i])) {
        headerLine = i;
        break;
      }
    }

    // 从起始行往下找下一个标题作为结束行
    let endLine = lines.length;
    for (let i = startLine + 1; i < lines.length; i++) {
      if (/^##\s*第\d+项/.test(lines[i]) || /^\s*第[一二三四五六七八九十百千\d]+条/.test(lines[i])) {
        endLine = i;
        break;
      }
    }
    setHighlightLines({ start: headerLine, end: endLine });
  }, [sourceContent]);

  const handleViewChunks = async (filePath: string) => {
    setChunksLoading(true);
    setChunksOpen(true);
    setChunksFilePath(filePath);
    setSelectedChunk(null);
    setHighlightLines(null);
    try {
      const [previewResult, chunksResult] = await Promise.all([
        kbApi.fetchDocumentPreview(filePath),
        kbApi.fetchDocumentChunks(filePath),
      ]);
      setRawContent(previewResult.content);
      setChunks(chunksResult.chunks as ChunkItem[]);
    } catch (err) {
      message.error(`加载失败: ${err}`);
    } finally {
      setChunksLoading(false);
    }
  };

  const handleStartEdit = () => {
    setEditContent(rawContent);
    setEditing(true);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditContent('');
  };

  const handleSaveEdit = async () => {
    setSaving(true);
    try {
      await kbApi.saveDocument(chunksFilePath, editContent);
      setRawContent(editContent);
      setEditing(false);
      message.success('保存成功，请重建索引以生效');
    } catch (err) {
      message.error(`保存失败: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  const [selectedDir, setSelectedDir] = useState<string | null>(null);

  // 从文档列表构建目录树
  const treeData = useMemo(() => {
    const dirMap = new Map<string, { count: number; clauses: number }>();
    documents.forEach(doc => {
      const parts = doc.file_path.split('/');
      const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '根目录';
      const existing = dirMap.get(dir) || { count: 0, clauses: 0 };
      existing.count++;
      existing.clauses += doc.clause_count;
      dirMap.set(dir, existing);
    });

    return Array.from(dirMap.entries()).map(([dir, info]) => {
      const dirName = dir.split('/').pop() || dir;
      const docCount = info.count;
      return {
        key: dir,
        title: (
          <span>
            <FolderOutlined style={{ marginRight: 6, color: token.colorPrimary }} />
            <span>{dirName}</span>
            <Tag style={{ marginLeft: 8 }}>{docCount} 篇</Tag>
            <Tag color="orange" style={{ marginLeft: 4 }}>{info.clauses} 条</Tag>
          </span>
        ),
      };
    });
  }, [documents]);

  // 根据选中目录过滤文档
  const filteredDocuments = useMemo(() => {
    if (!selectedDir) return documents;
    return documents.filter(doc => doc.file_path.startsWith(selectedDir + '/'));
  }, [documents, selectedDir]);

  const handleTreeSelect = (selectedKeys: React.Key[]) => {
    if (selectedKeys.length > 0) {
      setSelectedDir(selectedKeys[0] as string);
    } else {
      setSelectedDir(null);
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
        <Button type="link" icon={<UnorderedListOutlined />} onClick={() => handleViewChunks(record.file_path)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <div style={isMobile ? { overflowX: 'hidden' } : undefined}>
      <Title level={4} className="mb-16">知识库管理</Title>

      <Row gutter={isMobile ? [8, 8] : [16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size={isMobile ? 'small' : undefined}>
            <Statistic title="文档数量" value={documents.length} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size={isMobile ? 'small' : undefined}>
            <Statistic title="向量库文档" value={indexStatus?.document_count || 0} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size={isMobile ? 'small' : undefined}>
            <Statistic
              title="BM25 状态"
              value={indexStatus?.bm25?.loaded ? '已加载' : '未加载'}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size={isMobile ? 'small' : undefined} style={isMobile ? { overflow: 'hidden' } : undefined}>
            <Statistic
              title="当前版本"
              value={activeVersion || '-'}
              valueStyle={isMobile ? { fontSize: 14 } : undefined}
              suffix={activeVersion && <Tag color="blue" style={{ marginLeft: 4, fontSize: 11 }}>{versions.find(v => v.version_id === activeVersion)?.description || '当前激活'}</Tag>}
            />
          </Card>
        </Col>
      </Row>

      <Space wrap style={{ marginBottom: 16 }}>
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
          {(() => {
            const match = taskProgress.match(/(\d+)\s*\/\s*(\d+)/);
            const percent = match ? Math.round((parseInt(match[1]) / parseInt(match[2])) * 100) : (taskStatus === 'pending' ? 0 : undefined);
            return (
              <>
                <Progress
                  percent={percent}
                  status={percent === undefined ? 'active' : undefined}
                  format={percent !== undefined ? undefined : () => taskProgress || '处理中...'}
                />
                <Text type="secondary">
                  {taskStatus === 'pending' ? '等待中...' : taskProgress || '处理中...'}
                </Text>
              </>
            );
          })()}
        </Card>
      )}

      <Card>
        {isMobile ? (
          <Tabs
            size="small"
            defaultActiveKey="docs"
            items={[
              {
                key: 'tree',
                label: '法规分类',
                children: (
                  <>
                    <Tree
                      showLine
                      treeData={treeData}
                      onSelect={handleTreeSelect}
                      selectedKeys={selectedDir ? [selectedDir] : []}
                      defaultExpandAll
                    />
                    {selectedDir && (
                      <div style={{ padding: '8px 0' }}>
                        <Button type="link" size="small" onClick={() => setSelectedDir(null)}>
                          显示全部
                        </Button>
                      </div>
                    )}
                  </>
                ),
              },
              {
                key: 'docs',
                label: `文档 (${filteredDocuments.length})`,
                children: (
                  <Table
                    dataSource={filteredDocuments}
                    columns={columns}
                    rowKey="name"
                    loading={loading}
                    pagination={{ pageSize: 20 }}
                    size="small"
                    scroll={{ x: 'max-content' }}
                  />
                ),
              },
            ]}
          />
        ) : (
          <Row style={{ minHeight: 400 }}>
            <Col
              span={6}
              style={{
                borderRight: `1px solid ${token.colorBorderSecondary}`,
                maxHeight: 'calc(100vh - var(--header-height) - 256px)',
                overflow: 'auto',
              }}
            >
              <div className="section-header" style={{ marginBottom: 8 }}>
                法规分类
              </div>
              <Tree
                showLine
                treeData={treeData}
                onSelect={handleTreeSelect}
                selectedKeys={selectedDir ? [selectedDir] : []}
                defaultExpandAll
              />
            </Col>

            <Col span={18}>
              <div className="section-header flex-between" style={{ marginBottom: 8 }}>
                <span>
                  {selectedDir
                    ? <><FileOutlined style={{ marginRight: 6 }} />{selectedDir.split('/').pop()}</>
                    : <><DatabaseOutlined style={{ marginRight: 6 }} />全部文档 ({documents.length})</>}
                </span>
                {selectedDir && (
                  <Button type="link" size="small" onClick={() => setSelectedDir(null)}>
                    显示全部
                  </Button>
                )}
              </div>
              <Table
                dataSource={filteredDocuments}
                columns={columns}
                rowKey="name"
                loading={loading}
                pagination={{ pageSize: 20 }}
                size="small"
              />
            </Col>
          </Row>
        )}
      </Card>

      <Modal
        title={<span title={chunksDocName} style={{ display: 'inline-block', maxWidth: isMobile ? '60vw' : 'calc(95vw - var(--content-padding) * 6)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{`分块验证 — ${chunksDocName}`}</span>}
        open={chunksOpen}
        onCancel={() => { setChunksOpen(false); setSelectedChunk(null); setEditing(false); setHighlightLines(null); }}
        footer={null}
        width={isMobile ? '100%' : '95vw'}
        style={isMobile ? { top: 0, maxWidth: '100vw', paddingBottom: 0 } : { top: 20, maxWidth: 1600 }}
        styles={{ body: { padding: 0, height: isMobile ? '100vh' : 'calc(100vh - var(--header-height) - 56px)' } }}
      >
        {chunksLoading ? (
          <div className="empty-state"><Spin size="large" /></div>
        ) : isMobile ? (
          <Tabs
            size="small"
            defaultActiveKey="chunks"
            items={[
              {
                key: 'source',
                label: '原文',
                children: (
                  <div style={{ height: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column' }}>
                    <div className="section-header flex-between" style={{ flexShrink: 0, background: token.colorFillQuaternary, padding: '6px 12px' }}>
                      <Text strong style={{ fontSize: token.fontSize }}>原文</Text>
                      <Space size={4}>
                        {editing ? (
                          <>
                            <Button size="small" type="primary" loading={saving} onClick={handleSaveEdit}>保存</Button>
                            <Button size="small" onClick={handleCancelEdit}>取消</Button>
                          </>
                        ) : (
                          <Button size="small" onClick={handleStartEdit}>编辑</Button>
                        )}
                      </Space>
                    </div>
                    <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
                      {editing ? (
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          style={{
                            width: '100%', height: '100%', border: 'none', padding: 8,
                            fontSize: token.fontSizeSM, lineHeight: 1.6, fontFamily: 'inherit', resize: 'none', outline: 'none',
                          }}
                        />
                      ) : (
                        <div ref={sourceRef} className="markdown-body" style={{ margin: 0, fontSize: token.fontSizeSM, lineHeight: 1.6 }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{sourceContent}</ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </div>
                ),
              },
              {
                key: 'chunks',
                label: `条款 (${chunks.length})`,
                children: (
                  <div style={{ height: 'calc(100vh - 120px)', overflow: 'auto', padding: '0 12px 12px' }}>
                    {selectedChunk ? (
                      <>
                        <Button size="small" style={{ marginBottom: 12 }} onClick={() => { setSelectedChunk(null); setHighlightLines(null); }}>
                          &larr; 返回列表
                        </Button>
                        <Descriptions size="small" bordered column={1} style={{ marginBottom: 12 }}>
                          <Descriptions.Item label="法规名称">{selectedChunk.law_name}</Descriptions.Item>
                          <Descriptions.Item label="条款号">{selectedChunk.article_number}</Descriptions.Item>
                          <Descriptions.Item label="分类"><Tag>{selectedChunk.category}</Tag></Descriptions.Item>
                          <Descriptions.Item label="层级路径">{selectedChunk.hierarchy_path}</Descriptions.Item>
                          <Descriptions.Item label="来源文件">{selectedChunk.source_file}</Descriptions.Item>
                          {selectedChunk.doc_number && <Descriptions.Item label="发文号">{selectedChunk.doc_number}</Descriptions.Item>}
                          {selectedChunk.issuing_authority && <Descriptions.Item label="发文机关">{selectedChunk.issuing_authority}</Descriptions.Item>}
                          {Object.entries(selectedChunk)
                            .filter(([k]) => !['law_name', 'article_number', 'category', 'hierarchy_path', 'source_file', 'doc_number', 'issuing_authority', 'effective_date', 'text', 'text_length', '_node_content', '_node_type', 'doc_id', 'document_id', 'ref_doc_id'].includes(k))
                            .map(([k, v]) => v && <Descriptions.Item key={k} label={k}><Tag color="blue">{String(v)}</Tag></Descriptions.Item>)
                          }
                          <Descriptions.Item label="字数">{selectedChunk.text_length}</Descriptions.Item>
                        </Descriptions>
                        <div className="markdown-body" style={{ background: token.colorFillQuaternary, padding: 12, borderRadius: 6, fontSize: token.fontSize, lineHeight: 1.8, overflow: 'auto' }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{selectedChunk.text}</ReactMarkdown>
                        </div>
                      </>
                    ) : (
                      <Table
                        dataSource={chunks}
                        rowKey={(_, i) => String(i)}
                        size="small"
                        pagination={false}
                        scroll={{ x: 'max-content' }}
                        onRow={(record) => ({
                          onClick: () => { setSelectedChunk(record); locateInSource(record.text); },
                          style: { cursor: 'pointer' },
                        })}
                        columns={[
                          { title: '#', key: 'idx', width: 40, render: (_: unknown, __: unknown, i: number) => i + 1 },
                          { title: '条款号', dataIndex: 'article_number', key: 'article_number', width: 90, ellipsis: true, render: (v: string) => v === '未知' ? <Text type="secondary">{v}</Text> : v },
                          { title: '分类', dataIndex: 'category', key: 'category', width: 80, ellipsis: true, render: (v: string) => <Tag>{v}</Tag> },
                          { title: '字数', dataIndex: 'text_length', key: 'text_length', width: 60 },
                          { title: '内容摘要', key: 'preview', render: (_: unknown, r: ChunkItem) => <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{r.text.slice(0, 80)}...</Text> },
                        ]}
                      />
                    )}
                  </div>
                ),
              },
            ]}
          />
        ) : (
          <div style={{ display: 'flex', height: '100%' }}>
            <div style={{ width: '45%', height: '100%', borderRight: `1px solid ${token.colorBorderSecondary}`, display: 'flex', flexDirection: 'column' }}>
              <div className="section-header flex-between" style={{ flexShrink: 0, background: token.colorFillQuaternary, padding: '6px 12px' }}>
                <Text strong style={{ fontSize: token.fontSize }}>原文</Text>
                <Space size={4}>
                  {editing ? (
                    <>
                      <Button size="small" type="primary" loading={saving} onClick={handleSaveEdit}>保存</Button>
                      <Button size="small" onClick={handleCancelEdit}>取消</Button>
                    </>
                  ) : (
                    <Button size="small" onClick={handleStartEdit}>编辑</Button>
                  )}
                </Space>
              </div>
              <div style={{ flex: 1, overflow: 'auto', padding: '8px 12px' }}>
                {editing ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    style={{
                      width: '100%', height: '100%', border: 'none', padding: 8,
                      fontSize: token.fontSizeSM, lineHeight: 1.6, fontFamily: 'inherit', resize: 'none', outline: 'none',
                    }}
                  />
                ) : (
                  <div ref={sourceRef} className="markdown-body" style={{ margin: 0, fontSize: token.fontSizeSM, lineHeight: 1.6 }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{sourceContent}</ReactMarkdown>
                  </div>
                )}
              </div>
            </div>

            <div style={{ width: '55%', height: '100%', display: 'flex', flexDirection: 'column' }}>
              <div className="section-header" style={{ flexShrink: 0 }}>
                提取条款 ({chunks.length})
              </div>
              {selectedChunk ? (
                <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
                  <Button size="small" style={{ marginBottom: 12 }} onClick={() => { setSelectedChunk(null); setHighlightLines(null); }}>
                    &larr; 返回列表
                  </Button>
                  <Descriptions size="small" bordered column={1} style={{ marginBottom: 12 }}>
                    <Descriptions.Item label="法规名称">{selectedChunk.law_name}</Descriptions.Item>
                    <Descriptions.Item label="条款号">{selectedChunk.article_number}</Descriptions.Item>
                    <Descriptions.Item label="分类"><Tag>{selectedChunk.category}</Tag></Descriptions.Item>
                    <Descriptions.Item label="层级路径">{selectedChunk.hierarchy_path}</Descriptions.Item>
                    <Descriptions.Item label="来源文件">{selectedChunk.source_file}</Descriptions.Item>
                    {selectedChunk.doc_number && <Descriptions.Item label="发文号">{selectedChunk.doc_number}</Descriptions.Item>}
                    {selectedChunk.issuing_authority && <Descriptions.Item label="发文机关">{selectedChunk.issuing_authority}</Descriptions.Item>}
                    {Object.entries(selectedChunk)
                      .filter(([k]) => !['law_name', 'article_number', 'category', 'hierarchy_path', 'source_file', 'doc_number', 'issuing_authority', 'effective_date', 'text', 'text_length', '_node_content', '_node_type', 'doc_id', 'document_id', 'ref_doc_id'].includes(k))
                      .map(([k, v]) => v && <Descriptions.Item key={k} label={k}><Tag color="blue">{String(v)}</Tag></Descriptions.Item>)
                    }
                    <Descriptions.Item label="字数">{selectedChunk.text_length}</Descriptions.Item>
                  </Descriptions>
                  <div className="markdown-body" style={{ background: token.colorFillQuaternary, padding: 12, borderRadius: 6, fontSize: token.fontSize, lineHeight: 1.8, maxHeight: 'calc(100vh - var(--header-height) - 336px)', overflow: 'auto' }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{selectedChunk.text}</ReactMarkdown>
                  </div>
                </div>
              ) : (
                <div style={{ flex: 1, overflow: 'auto' }}>
                  <Table
                    dataSource={chunks}
                    rowKey={(_, i) => String(i)}
                    size="small"
                    pagination={false}
                    scroll={{ x: 'max-content' }}
                    onRow={(record) => ({
                      onClick: () => { setSelectedChunk(record); locateInSource(record.text); },
                      style: { cursor: 'pointer' },
                    })}
                    columns={[
                      { title: '#', key: 'idx', width: 40, render: (_: unknown, __: unknown, i: number) => i + 1 },
                      { title: '条款号', dataIndex: 'article_number', key: 'article_number', width: 90, ellipsis: true, render: (v: string) => v === '未知' ? <Text type="secondary">{v}</Text> : v },
                      { title: '分类', dataIndex: 'category', key: 'category', width: 80, ellipsis: true, render: (v: string) => <Tag>{v}</Tag> },
                      { title: '字数', dataIndex: 'text_length', key: 'text_length', width: 60 },
                      { title: '内容摘要', key: 'preview', render: (_: unknown, r: ChunkItem) => <Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{r.text.slice(0, 80)}...</Text> },
                    ]}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      <Modal
        title="创建新版本"
        open={createVersionModalOpen}
        onOk={handleCreateVersion}
        onCancel={() => { setCreateVersionModalOpen(false); setVersionDescription(''); }}
        okText="创建"
        cancelText="取消"
        width={isMobile ? '100%' : MODAL_SM}
        style={isMobile ? { top: 40, maxWidth: '100vw', margin: '0 12px' } : undefined}
      >
        <p style={{ color: token.colorTextSecondary, marginBottom: 12 }}>
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
        size={isMobile ? '100%' : DRAWER_MD}
      >
        <Table
          dataSource={versions}
          rowKey="version_id"
          pagination={false}
          size="small"
          scroll={{ x: 'max-content' }}
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
