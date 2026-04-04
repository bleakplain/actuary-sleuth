import React, { useState, useMemo } from 'react';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownOutlined,
  RightOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import type { TraceSpan, TraceData } from '../types';

/* ── category visual config ── */

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  root: { label: 'Root', color: '#8c8c8c', bg: '#fafafa' },
  preprocessing: { label: '预处理', color: '#722ed1', bg: '#f9f0ff' },
  retrieval: { label: '检索', color: '#1677ff', bg: '#e6f4ff' },
  rerank: { label: '重排序', color: '#fa8c16', bg: '#fff7e6' },
  llm: { label: 'LLM', color: '#52c41a', bg: '#f6ffed' },
};

function getCategoryStyle(category: string) {
  return CATEGORY_CONFIG[category] || { label: category, color: '#8c8c8c', bg: '#fafafa' };
}

/* ── helpers ── */

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

/* ── copy button ── */

function CopyBtn({ text }: { text: string }) {
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

/* ── collapsible text block ── */

function CollapsibleText({ label, text, bg }: { label: string; text: string; bg: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;

  const lines = text.split('\n');
  const isLong = lines.length > 6 || text.length > 500;
  const preview = isLong ? lines.slice(0, 6).join('\n') + '\n...' : text;

  return (
    <div style={{ marginTop: 8 }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          fontSize: 11, color: '#8c8c8c', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3,
          userSelect: 'none',
        }}
      >
        {isLong && (expanded ? <DownOutlined style={{ fontSize: 9 }} /> : <RightOutlined style={{ fontSize: 9 }} />)}
        <span style={{ fontWeight: 500 }}>{label}</span>
        <CopyBtn text={text} />
      </div>
      <pre style={{
        margin: 0, padding: '8px 10px', background: bg, borderRadius: 6,
        fontSize: 11, lineHeight: 1.6, overflow: 'auto', maxHeight: expanded ? 400 : undefined,
        fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}>
        {expanded ? text : preview}
      </pre>
    </div>
  );
}

/* ── retrieval results list with score heat indicator ── */

const RETRIEVAL_COLLAPSE_THRESHOLD = 3;

function RetrievalResults({ results, maxScore }: {
  results: Array<Record<string, unknown>>;
  maxScore?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!results || results.length === 0) return null;

  const isLong = results.length > RETRIEVAL_COLLAPSE_THRESHOLD;
  const shown = expanded ? results : results.slice(0, RETRIEVAL_COLLAPSE_THRESHOLD);
  const hidden = results.length - RETRIEVAL_COLLAPSE_THRESHOLD;
  const topScore = maxScore != null ? maxScore : (results[0]?.score as number) || 1;

  return (
    <div style={{ marginTop: 4 }}>
      {shown.map((r, i) => {
        const score = r.score != null ? Number(r.score) : 0;
        const heat = Math.min(score / topScore, 1);
        return (
          <div key={i} style={{
            padding: '5px 8px', marginBottom: 3, background: '#fff', borderRadius: 4,
            border: '1px solid #f0f0f0',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 1 }}>
              <span style={{ fontSize: 12, color: '#262626', fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {String(r.law_name || '未知法规')} {String(r.article_number || '')}
              </span>
              <span style={{
                fontSize: 11, fontVariantNumeric: 'tabular-nums', color: '#595959',
                background: `rgba(22, 119, 255, ${0.08 + heat * 0.15})`,
                padding: '1px 6px', borderRadius: 3, flexShrink: 0,
              }}>
                {score > 0 ? score.toFixed(4) : '-'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c', lineHeight: 1.5 }}>
              {String(r.content_preview || '')}
            </div>
          </div>
        );
      })}
      {isLong && !expanded && (
        <div onClick={() => setExpanded(true)}
          style={{ textAlign: 'center', padding: '4px 0', cursor: 'pointer', fontSize: 11, color: '#1677ff' }}>
          展开剩余 {hidden} 条
        </div>
      )}
      {isLong && expanded && (
        <div onClick={() => setExpanded(false)}
          style={{ textAlign: 'center', padding: '4px 0', cursor: 'pointer', fontSize: 11, color: '#bfbfbf' }}>
          收起
        </div>
      )}
    </div>
  );
}

/* ── rerank results list ── */

function RerankResults({ results }: { results: Array<Record<string, unknown>> }) {
  if (!results || results.length === 0) return null;
  return (
    <div style={{ marginTop: 4 }}>
      {results.map((r, i) => (
        <div key={i} style={{
          padding: '4px 8px', marginBottom: 2, background: '#fff',
          borderRadius: 4, border: '1px solid #f0f0f0',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#fa8c16', width: 20, textAlign: 'center' }}>
            #{String(r.rank || i + 1)}
          </span>
          <span style={{ fontSize: 12, color: '#262626', flex: 1 }}>
            {String(r.law_name || '')} {String(r.article_number || '')}
          </span>
          <span style={{ fontSize: 11, color: '#595959', fontVariantNumeric: 'tabular-nums' }}>
            {r.rerank_score != null ? Number(r.rerank_score).toFixed(2) : '-'}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── section header ── */

function SectionHeader({ label, count, shown }: { label: string; count?: number; shown?: number }) {
  let detail: string | undefined;
  if (count != null && shown != null && shown < count) {
    detail = `${count} 条，预览 ${shown} 条`;
  } else if (count != null) {
    detail = `${count} 条`;
  }
  return (
    <div style={{
      fontSize: 11, color: '#595959', marginBottom: 4, marginTop: 10,
      fontWeight: 500, display: 'flex', alignItems: 'center', gap: 4,
    }}>
      <span>{label}</span>
      {detail && <span style={{ fontSize: 10, color: '#bfbfbf' }}>({detail})</span>}
    </div>
  );
}

/* ── metadata table ── */

function MetaTable({ entries }: { entries: [string, unknown][] }) {
  if (entries.length === 0) return null;
  return (
    <div style={{
      margin: '0 0 8px', fontSize: 11, lineHeight: 1.8, color: '#8c8c8c',
    }}>
      {entries.map(([k, v]) => (
        <span key={k} style={{ marginRight: 16 }}>
          <span style={{ color: '#bfbfbf' }}>{k}:</span>{' '}
          <span style={{ color: '#595959' }}>{String(v)}</span>
        </span>
      ))}
    </div>
  );
}

/* ── span detail panel ── */

function SpanDetails({ span, depth }: { span: TraceSpan; depth: number }) {
  const catStyle = getCategoryStyle(span.category);
  const cat = span.category;
  const metaEntries = span.metadata && Object.keys(span.metadata).length > 0
    ? Object.entries(span.metadata).filter(([k]) => k !== 'prompt') : [];
  const out = span.output && typeof span.output === 'object' ? span.output : null;

  return (
    <div style={{
      marginLeft: depth * 16, paddingLeft: 44, paddingRight: 12, paddingBottom: 8,
      borderLeft: `3px solid ${catStyle.color}`,
      background: catStyle.bg,
    }}>
      <MetaTable entries={metaEntries} />

      {/* retrieval */}
      {cat === 'retrieval' && out && (
        <>
          {out.per_query_results && out.per_query_results.length > 0 && (
            <>
              <SectionHeader label="分查询检索明细" />
              {(out.per_query_results as Array<Record<string, unknown>>).map((qr, qi) => (
                <div key={qi} style={{
                  marginBottom: 8, padding: '6px 8px', background: '#fff',
                  borderRadius: 4, border: '1px solid #f0f0f0',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: '0 5px',
                      borderRadius: 3, background: qi === 0 ? '#e6f4ff' : '#f0f0f0',
                      color: qi === 0 ? '#1677ff' : '#595959',
                    }}>
                      {String(qr.label || `查询 ${qi + 1}`)}
                    </span>
                    <span style={{ fontSize: 11, color: '#8c8c8c', fontStyle: 'italic' }}>
                      {String(qr.query || '')}
                    </span>
                  </div>
                  {qr.vector_top && (qr.vector_top as Array<Record<string, unknown>>).length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: '#bfbfbf' }}>
                        向量检索 ({qr.vector_count} 条)
                      </span>
                      <RetrievalResults results={qr.vector_top as Array<Record<string, unknown>>} />
                    </div>
                  )}
                  {qr.keyword_top && (qr.keyword_top as Array<Record<string, unknown>>).length > 0 && (
                    <div>
                      <span style={{ fontSize: 10, color: '#bfbfbf' }}>
                        BM25 检索 ({qr.keyword_count} 条)
                      </span>
                      <RetrievalResults results={qr.keyword_top as Array<Record<string, unknown>>} />
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
          {out.fusion_results && out.fusion_results.length > 0 && (
            <>
              <SectionHeader label="RRF 融合结果" count={out.fusion_result_count} shown={out.fusion_results.length} />
              <RetrievalResults results={out.fusion_results as Array<Record<string, unknown>>} maxScore={undefined} />
            </>
          )}
          {!out.per_query_results && out.results && (
            <RetrievalResults results={out.results as Array<Record<string, unknown>>} />
          )}
        </>
      )}

      {/* rerank */}
      {cat === 'rerank' && (
        <>
          {span.input && typeof span.input === 'object' && 'prompt' in span.input && (
            <CollapsibleText label="Rerank Prompt" text={String(span.input.prompt)} bg="#fff7e6" />
          )}
          {span.output && typeof span.output === 'object' && 'raw_response' in span.output && (
            <CollapsibleText label="LLM 回复" text={String(span.output.raw_response)} bg="#fafafa" />
          )}
          {span.output && typeof span.output === 'object' && 'results' in span.output && (
            <RerankResults results={span.output.results as Array<Record<string, unknown>>} />
          )}
        </>
      )}

      {/* llm */}
      {cat === 'llm' && (
        <>
          {span.input && typeof span.input === 'object' && 'system_prompt' in span.input && (
            <CollapsibleText label="System Prompt" text={String(span.input.system_prompt)} bg="#fafafa" />
          )}
          {span.input && typeof span.input === 'object' && 'user_prompt' in span.input && (
            <CollapsibleText label="User Prompt（含检索上下文）" text={String(span.input.user_prompt)} bg="#f6ffed" />
          )}
          {span.output && typeof span.output === 'object' && 'answer' in span.output && (
            <CollapsibleText label="LLM 回复" text={String(span.output.answer)} bg="#f6ffed" />
          )}
        </>
      )}

      {/* root */}
      {cat === 'root' && (
        <>
          {span.input && typeof span.input === 'object' && span.input.question && (
            <div style={{ fontSize: 12, color: '#595959', lineHeight: 1.6 }}>
              <span style={{ color: '#bfbfbf' }}>问题:</span> {String(span.input.question)}
            </div>
          )}
          {out && out.answer && (
            <CollapsibleText label="最终回复" text={String(out.answer)} bg="#f5f5f5" />
          )}
        </>
      )}

      {/* fallback */}
      {cat !== 'retrieval' && cat !== 'rerank' && cat !== 'llm' && cat !== 'root' && (
        <>
          <CollapsibleText label="Input" text={JSON.stringify(span.input ?? {}, null, 2)} bg="#fafafa" />
          <CollapsibleText label="Output" text={JSON.stringify(span.output ?? {}, null, 2)} bg="#f6ffed" />
        </>
      )}

      {span.error && (
        <div style={{
          marginTop: 6, padding: '6px 10px', background: '#fff2f0',
          borderRadius: 6, fontSize: 12, color: '#cf1322',
        }}>
          {span.error}
        </div>
      )}
    </div>
  );
}

/* ── span row ── */

function SpanRow({ span, depth, maxDuration }: {
  span: TraceSpan; depth: number; maxDuration: number;
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const cat = getCategoryStyle(span.category);
  const isError = span.status === 'error';
  const hasChildren = span.children && span.children.length > 0;
  const barWidth = maxDuration > 0 ? Math.max(2, (span.duration_ms / maxDuration) * 100) : 2;

  return (
    <div>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '5px 12px', cursor: 'pointer',
          borderRadius: 6,
          background: expanded ? cat.bg : 'transparent',
          transition: 'background 0.15s',
          marginLeft: depth * 16,
        }}
        onMouseEnter={(e) => { if (!expanded) e.currentTarget.style.background = '#fafafa'; }}
        onMouseLeave={(e) => { if (!expanded) e.currentTarget.style.background = 'transparent'; }}
      >
        <span style={{ fontSize: 10, color: '#bfbfbf', width: 12, flexShrink: 0, textAlign: 'center' }}>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </span>
        {isError ? (
          <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 14, flexShrink: 0 }} />
        ) : (
          <CheckCircleFilled style={{ color: cat.color, fontSize: 14, flexShrink: 0 }} />
        )}
        <span style={{ fontWeight: 500, fontSize: 13, color: '#262626', flexShrink: 0 }}>
          {span.name}
        </span>
        <span style={{
          fontSize: 10, color: '#bfbfbf',
          fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
          flexShrink: 0,
        }}>
          {span.span_id}<CopyBtn text={span.span_id} />
        </span>
        <span style={{
          fontSize: 10, color: cat.color, background: cat.bg,
          padding: '0 6px', borderRadius: 3, lineHeight: '18px', flexShrink: 0,
        }}>
          {cat.label}
        </span>
        <div style={{ flex: 1, minWidth: 40, display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            height: 4, borderRadius: 2,
            background: isError ? '#ffccc7' : cat.color,
            opacity: 0.4,
            width: `${barWidth}%`,
            minWidth: 4,
          }} />
        </div>
        <span style={{
          fontSize: 11, color: '#8c8c8c', fontVariantNumeric: 'tabular-nums',
          flexShrink: 0, minWidth: 48, textAlign: 'right',
        }}>
          {formatDuration(span.duration_ms)}
        </span>
      </div>

      {expanded && <SpanDetails span={span} depth={depth} />}

      {expanded && hasChildren && (
        <div>
          {span.children.map((child) => (
            <SpanRow key={child.span_id} span={child} depth={depth + 1} maxDuration={maxDuration} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── build tree ── */

function buildSpanTree(spans: TraceSpan[]): TraceSpan[] {
  const map = new Map<string, TraceSpan>();
  const roots: TraceSpan[] = [];
  for (const s of spans) {
    map.set(s.span_id, { ...s, children: [] });
  }
  for (const s of spans) {
    const node = map.get(s.span_id)!;
    if (s.parent_span_id && map.has(s.parent_span_id)) {
      map.get(s.parent_span_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

/* ── main panel ── */

interface Props {
  trace: TraceData | null;
  loading?: boolean;
}

export default function TracePanel({ trace, loading }: Props) {
  if (loading) {
    return (
      <div style={{ padding: '40px 16px', textAlign: 'center' }}>
        <span style={{ fontSize: 13, color: '#8c8c8c' }}>加载中...</span>
      </div>
    );
  }

  if (!trace) {
    return (
      <div style={{ padding: '40px 16px', textAlign: 'center' }}>
        <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.25 }}>&#x1f50d;</div>
        <span style={{ fontSize: 13, color: '#8c8c8c' }}>暂无 Trace 数据</span>
        <div style={{ fontSize: 12, color: '#bfbfbf', marginTop: 4 }}>
          发送新消息后将自动记录链路
        </div>
      </div>
    );
  }

  const tree = useMemo(() => buildSpanTree(trace.spans), [trace.spans]);
  const maxDuration = useMemo(() => {
    const findMax = (spans: TraceSpan[]): number =>
      Math.max(...spans.map((s) => Math.max(s.duration_ms, findMax(s.children || []))));
    return findMax(tree);
  }, [tree]);

  return (
    <div style={{ padding: '8px 0' }}>
      {/* summary bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 16px', borderBottom: '1px solid #f0f0f0',
        flexWrap: 'wrap',
      }}>
        <span style={{
          fontSize: 11, color: '#595959', background: '#f5f5f5',
          padding: '2px 8px', borderRadius: 10,
          fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
        }}>
          trace:{' '}{trace.trace_id}<CopyBtn text={trace.trace_id} />
        </span>
        <span style={{
          fontSize: 11, color: '#fff', background: '#262626',
          padding: '2px 8px', borderRadius: 10,
        }}>
          {trace.summary.span_count} 步骤
        </span>
        <span style={{
          fontSize: 11, color: '#389e0d', background: '#f6ffed',
          padding: '2px 8px', borderRadius: 10,
        }}>
          {trace.summary.llm_call_count} 次 LLM
        </span>
        <span style={{
          fontSize: 11, color: '#595959', background: '#f5f5f5',
          padding: '2px 8px', borderRadius: 10,
        }}>
          {formatDuration(trace.summary.total_duration_ms)}
        </span>
        {trace.summary.error_count > 0 && (
          <span style={{
            fontSize: 11, color: '#fff', background: '#ff4d4f',
            padding: '2px 8px', borderRadius: 10,
          }}>
            {trace.summary.error_count} 错误
          </span>
        )}
      </div>

      {/* span tree */}
      <div style={{ padding: '8px 0' }}>
        {tree.map((root) => (
          <SpanRow key={root.span_id} span={root} depth={0} maxDuration={maxDuration} />
        ))}
      </div>
    </div>
  );
}
