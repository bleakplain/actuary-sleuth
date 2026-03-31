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

export async function fetchIndexStatus(): Promise<IndexStatus> {
  const { data } = await client.get('/api/kb/status');
  return data;
}
