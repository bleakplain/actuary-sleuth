import client from './client';
import type { ComplianceReport } from '../types';

export async function checkProduct(params: {
  product_name: string;
  category: string;
  params: Record<string, string | number>;
}): Promise<ComplianceReport> {
  const { data } = await client.post('/api/compliance/check/product', params);
  return data;
}

export async function checkDocument(params: {
  document_content: string;
  product_name?: string;
}): Promise<ComplianceReport> {
  const { data } = await client.post('/api/compliance/check/document', params);
  return data;
}

export async function fetchComplianceReports(): Promise<ComplianceReport[]> {
  const { data } = await client.get('/api/compliance/reports');
  return data;
}

export async function fetchComplianceReport(id: string): Promise<ComplianceReport> {
  const { data } = await client.get(`/api/compliance/reports/${id}`);
  return data;
}
