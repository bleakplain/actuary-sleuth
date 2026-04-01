import client from './client';
import type { Document, IndexStatus, TaskStatus } from '../types';

export async function fetchDocuments(): Promise<Document[]> {
  const { data } = await client.get('/api/kb/documents');
  return data;
}

export async function importDocuments(filePattern: string, filePath?: string): Promise<{ task_id: string }> {
  const { data } = await client.post('/api/kb/documents/import', {
    file_path: filePath || undefined,
    file_pattern: filePattern,
  });
  return data;
}

export async function rebuildIndex(filePattern: string, force: boolean): Promise<{ task_id: string }> {
  const { data } = await client.post('/api/kb/documents/rebuild', {
    file_pattern: filePattern,
    force,
  });
  return data;
}

export async function fetchTaskStatus(taskId: string): Promise<TaskStatus> {
  const { data } = await client.get(`/api/kb/tasks/${taskId}`);
  return data;
}

export async function fetchDocumentPreview(name: string): Promise<{ name: string; content: string; total_chars: number }> {
  const { data } = await client.get(`/api/kb/documents/${encodeURIComponent(name)}/preview`);
  return data;
}

export async function saveDocument(name: string, content: string): Promise<{ name: string; saved: boolean }> {
  const { data } = await client.put(`/api/kb/documents/${encodeURIComponent(name)}`, { content });
  return data;
}

export async function fetchDocumentChunks(name: string): Promise<{
  document_name: string;
  total_chunks: number;
  chunks: Array<{
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
  }>;
}> {
  const { data } = await client.get(`/api/kb/documents/${encodeURIComponent(name)}/chunks`);
  return data;
}

export async function fetchIndexStatus(): Promise<IndexStatus> {
  const { data } = await client.get('/api/kb/status');
  return data;
}

export interface KBVersion {
  version_id: string;
  created_at: string;
  document_count: number;
  chunk_count: number;
  active: boolean;
  description: string;
}

export async function fetchVersions(): Promise<{ versions: KBVersion[]; active_version: string }> {
  const { data } = await client.get('/api/kb/versions');
  return data;
}

export async function createVersion(description?: string): Promise<{ task_id: string }> {
  const { data } = await client.post('/api/kb/versions', { description: description || '' });
  return data;
}

export async function activateVersion(versionId: string): Promise<void> {
  await client.post(`/api/kb/versions/${versionId}/activate`);
}

export async function deleteVersion(versionId: string): Promise<void> {
  await client.delete(`/api/kb/versions/${versionId}`);
}
