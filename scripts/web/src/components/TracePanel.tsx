// Uses CSS variables (var(--ant-*)) instead of theme.useToken() to avoid
// threading token through many pure sub-components defined in this file.
import { useState, useMemo } from 'react';
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons';
import CopyBtn from './CopyBtn';
import type { TraceSpan, TraceData } from '../types';

import { TRACE_CATEGORY_COLORS } from '../constants/traceColors';

const CATEGORY_LABELS: Record<string, string> = {
  root: 'Root',
  preprocessing: '预处理',
  retrieval: '检索',
  rerank: '重排序',
  llm: '生成',
  memory: '记忆',
};

function getCategoryStyle(category: string) {
  const colors = TRACE_CATEGORY_COLORS[category];
  return { label: CATEGORY_LABELS[category] || category, color: colors?.color || 'var(--ant-color-text-secondary)', bg: colors?.bg || 'var(--ant-color-fill-quaternary)' };
}

/* ── helpers ── */

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function formatTimestamp(ts: number): string {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${mo}-${dd} ${h}:${m}:${s}.${ms}`;
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
          fontSize: 11, color: 'var(--ant-color-text-tertiary)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3,
          userSelect: 'none',
        }}
      >
        {isLong && (expanded ? <DownOutlined style={{ fontSize: 9 }} /> : <RightOutlined style={{ fontSize: 9 }} />)}
        <span style={{ fontWeight: 'var(--ant-font-weight-strong, 600)' }}>{label}</span>
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
            padding: '5px 8px', marginBottom: 3, background: 'var(--ant-color-bg-container)', borderRadius: 4,
            border: '1px solid var(--ant-color-border)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 1 }}>
              <span style={{ fontSize: 12, color: 'var(--ant-color-text)', fontWeight: 'var(--ant-font-weight-strong, 600)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {String(r.law_name || '未知法规')} {String(r.article_number || '')}
              </span>
              <span style={{
                fontSize: 11, fontVariantNumeric: 'tabular-nums', color: 'var(--ant-color-text-secondary)',
                background: `rgba(30, 64, 175, ${0.08 + heat * 0.15})`,
                padding: '1px 6px', borderRadius: 4, flexShrink: 0,
              }}>
                {score > 0 ? score.toFixed(4) : '-'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--ant-color-text-tertiary)', lineHeight: 1.5 }}>
              {String(r.content_preview || '')}
            </div>
          </div>
        );
      })}
      {isLong && !expanded && (
        <div onClick={() => setExpanded(true)}
          style={{ textAlign: 'center', padding: '4px 0', cursor: 'pointer', fontSize: 11, color: 'var(--ant-color-primary)' }}>
          展开剩余 {hidden} 条
        </div>
      )}
      {isLong && expanded && (
        <div onClick={() => setExpanded(false)}
          style={{ textAlign: 'center', padding: '4px 0', cursor: 'pointer', fontSize: 11, color: 'var(--ant-color-text-quaternary)' }}>
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
          padding: '4px 8px', marginBottom: 2, background: 'var(--ant-color-bg-container)',
          borderRadius: 4, border: '1px solid var(--ant-color-border)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 11, fontWeight: 'var(--ant-font-weight-strong, 600)', color: 'var(--ant-color-warning)', width: 20, textAlign: 'center' }}>
            #{String(r.rank || i + 1)}
          </span>
          <span style={{ fontSize: 12, color: 'var(--ant-color-text)', flex: 1 }}>
            {String(r.law_name || '')} {String(r.article_number || '')}
          </span>
          <span style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
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
      fontSize: 11, color: 'var(--ant-color-text-secondary)', marginBottom: 4, marginTop: 10,
      fontWeight: 'var(--ant-font-weight-strong, 600)', display: 'flex', alignItems: 'center', gap: 4,
    }}>
      <span>{label}</span>
      {detail && <span style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)' }}>({detail})</span>}
    </div>
  );
}

/* ── metadata table ── */

function MetaTable({ entries }: { entries: [string, unknown][] }) {
  if (entries.length === 0) return null;
  return (
    <div style={{
      margin: '0 0 8px', fontSize: 11, lineHeight: 1.8, color: 'var(--ant-color-text-tertiary)',
    }}>
      {entries.map(([k, v]) => (
        <span key={k} style={{ marginRight: 16 }}>
          <span style={{ color: 'var(--ant-color-text-quaternary)' }}>{k}:</span>{' '}
          <span style={{ color: 'var(--ant-color-text-secondary)' }}>{String(v)}</span>
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
                  marginBottom: 8, padding: '6px 8px', background: 'var(--ant-color-bg-container)',
                  borderRadius: 4, border: '1px solid var(--ant-color-border)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 11, fontWeight: 'var(--ant-font-weight-strong, 600)', padding: '0 5px',
                      borderRadius: 4, background: qi === 0 ? 'var(--ant-color-primary-bg)' : 'var(--ant-color-border)',
                      color: qi === 0 ? 'var(--ant-color-primary)' : 'var(--ant-color-text-secondary)',
                    }}>
                      {String(qr.label || `查询 ${qi + 1}`)}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--ant-color-text-tertiary)', fontStyle: 'italic' }}>
                      {String(qr.query || '')}
                    </span>
                  </div>
                  {qr.vector_top && (qr.vector_top as Array<Record<string, unknown>>).length > 0 && (
                    <div style={{ marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)' }}>
                        向量检索 ({qr.vector_count} 条)
                      </span>
                      <RetrievalResults results={qr.vector_top as Array<Record<string, unknown>>} />
                    </div>
                  )}
                  {qr.keyword_top && (qr.keyword_top as Array<Record<string, unknown>>).length > 0 && (
                    <div>
                      <span style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)' }}>
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
            <CollapsibleText label="Rerank Prompt" text={String(span.input.prompt)} bg="var(--ant-color-warning-bg)" />
          )}
          {span.output && typeof span.output === 'object' && 'raw_response' in span.output && (
            <CollapsibleText label="LLM 回复" text={String(span.output.raw_response)} bg="var(--ant-color-fill-quaternary)" />
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
            <CollapsibleText label="System Prompt" text={String(span.input.system_prompt)} bg="var(--ant-color-fill-quaternary)" />
          )}
          {span.input && typeof span.input === 'object' && 'user_prompt' in span.input && (
            <CollapsibleText label="User Prompt（含检索上下文）" text={String(span.input.user_prompt)} bg="var(--ant-color-success-bg)" />
          )}
          {span.output && typeof span.output === 'object' && 'answer' in span.output && (
            <CollapsibleText label="LLM 回复" text={String(span.output.answer)} bg="var(--ant-color-success-bg)" />
          )}
        </>
      )}

      {/* root */}
      {cat === 'root' && (
        <>
          {span.input && typeof span.input === 'object' && span.input.question && (
            <div style={{ fontSize: 12, color: 'var(--ant-color-text-secondary)', lineHeight: 1.6 }}>
              <span style={{ color: 'var(--ant-color-text-quaternary)' }}>问题:</span> {String(span.input.question)}
            </div>
          )}
          {out && out.answer && (
            <CollapsibleText label="最终回复" text={String(out.answer)} bg="var(--ant-color-fill-tertiary)" />
          )}
        </>
      )}

      {/* memory */}
      {cat === 'memory' && out && out.memory_count !== undefined && (
        <div style={{ fontSize: 11, color: 'var(--ant-color-text-secondary)', lineHeight: 1.6 }}>
          检索到 <span style={{ fontWeight: 'var(--ant-font-weight-strong, 600)', color: catStyle.color }}>{String(out.memory_count)}</span> 条记忆
          {out.has_profile ? '，含用户画像' : ''}
        </div>
      )}

      {/* fallback */}
      {cat !== 'retrieval' && cat !== 'rerank' && cat !== 'llm' && cat !== 'root' && cat !== 'memory' && (
        <>
          <CollapsibleText label="Input" text={JSON.stringify(span.input ?? {}, null, 2)} bg="var(--ant-color-fill-quaternary)" />
          <CollapsibleText label="Output" text={JSON.stringify(span.output ?? {}, null, 2)} bg="var(--ant-color-success-bg)" />
        </>
      )}

      {span.error && (
        <div style={{
          marginTop: 6, padding: '6px 10px', background: 'var(--ant-color-error-bg)',
          borderRadius: 6, fontSize: 12, color: 'var(--ant-color-error-text)',
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
        onMouseEnter={(e) => { if (!expanded) e.currentTarget.style.background = 'var(--ant-color-fill-quaternary)'; }}
        onMouseLeave={(e) => { if (!expanded) e.currentTarget.style.background = 'transparent'; }}
      >
        <span style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)', width: 12, flexShrink: 0, textAlign: 'center' }}>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </span>
        {isError ? (
          <CloseCircleFilled style={{ color: 'var(--ant-color-error)', fontSize: 14, flexShrink: 0 }} />
        ) : (
          <CheckCircleFilled style={{ color: cat.color, fontSize: 14, flexShrink: 0 }} />
        )}
        <span style={{ fontWeight: 'var(--ant-font-weight-strong, 600)', fontSize: 13, color: 'var(--ant-color-text)', flexShrink: 0 }}>
          {span.name}
        </span>
        <span style={{
          fontSize: 10, color: 'var(--ant-color-text-quaternary)', fontVariantNumeric: 'tabular-nums',
          fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
          flexShrink: 0,
        }}>
          {formatTimestamp(span.start_time)}
        </span>
        <span style={{
          fontSize: 10, color: 'var(--ant-color-text-quaternary)',
          fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
          flexShrink: 0,
        }}>
          {span.span_id}<CopyBtn text={span.span_id} />
        </span>
        <span style={{
          fontSize: 10, color: cat.color, background: cat.bg,
          padding: '0 6px', borderRadius: 4, lineHeight: '18px', flexShrink: 0,
        }}>
          {cat.label}
        </span>
        <div style={{ flex: 1, minWidth: 40, display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            height: 4, borderRadius: 2,
            background: isError ? 'var(--ant-color-error-bg-hover)' : cat.color,
            opacity: 0.4,
            width: `${barWidth}%`,
            minWidth: 4,
          }} />
        </div>
        <span style={{
          fontSize: 11, color: 'var(--ant-color-text-tertiary)', fontVariantNumeric: 'tabular-nums',
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
      <div className="empty-state">
        <span style={{ fontSize: 13 }}>加载中...</span>
      </div>
    );
  }

  if (!trace) {
    return (
      <div className="empty-state">
        <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.25 }}>&#x1f50d;</div>
        <span style={{ fontSize: 13 }}>暂无 Trace 数据</span>
        <div style={{ fontSize: 12, color: 'var(--ant-color-text-quaternary)', marginTop: 4 }}>
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
        padding: '8px 16px', borderBottom: '1px solid var(--ant-color-border)',
        flexWrap: 'wrap',
      }}>
        <span style={{
          fontSize: 11, color: 'var(--ant-color-text-secondary)', background: 'var(--ant-color-fill-tertiary)',
          padding: '2px 8px', borderRadius: 4,
          fontFamily: "'SF Mono', 'Menlo', 'Consolas', monospace",
        }}>
          Trace ID:{' '}{trace.trace_id}<CopyBtn text={trace.trace_id} />
        </span>
        <span style={{
          fontSize: 11, color: 'var(--ant-color-text-inverse)', background: 'var(--ant-color-bg-text-hover)',
          padding: '2px 8px', borderRadius: 4,
        }}>
          {trace.summary.span_count} 步骤
        </span>
        <span style={{
          fontSize: 11, color: 'var(--ant-color-success)', background: 'var(--ant-color-success-bg)',
          padding: '2px 8px', borderRadius: 4,
        }}>
          {trace.summary.llm_call_count} 次 LLM
        </span>
        <span style={{
          fontSize: 11, color: 'var(--ant-color-text-secondary)', background: 'var(--ant-color-fill-tertiary)',
          padding: '2px 8px', borderRadius: 4,
        }}>
          耗时 {formatDuration(trace.summary.total_duration_ms)}
        </span>
        {trace.summary.error_count > 0 && (
          <span style={{
            fontSize: 11, color: 'var(--ant-color-text-inverse)', background: 'var(--ant-color-error)',
            padding: '2px 8px', borderRadius: 4,
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
