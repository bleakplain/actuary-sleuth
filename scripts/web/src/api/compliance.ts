import client from './client';
import type { ComplianceReport, ParsedDocument } from '../types';

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

export async function deleteComplianceReport(id: string): Promise<void> {
  await client.delete(`/api/compliance/reports/${id}`);
}

export async function parseFile(file: File): Promise<ParsedDocument> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await client.post('/api/compliance/parse-file', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  });
  return data;
}

export async function parseRichText(htmlContent: string, productName?: string): Promise<ParsedDocument> {
  const { data } = await client.post('/api/compliance/parse-rich-text', {
    html_content: htmlContent,
    product_name: productName,
  }, { timeout: 180000 });
  return data;
}
