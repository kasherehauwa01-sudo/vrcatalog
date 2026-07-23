import type { Meta, Product, ProductDetail, ServiceLog } from '../types/catalog';

const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
const API = `${basePath}/api`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`Ошибка API: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  async meta(): Promise<Meta> { return request<Meta>(`${API}/meta`); },
  async filters(): Promise<Record<string,string[]>> { return request<Record<string,string[]>>(`${API}/filters`); },
  async products(params: URLSearchParams): Promise<Product[]> { return request<Product[]>(`${API}/products?${params}`); },
  async productCount(params: URLSearchParams): Promise<{count:number}> { return request<{count:number}>(`${API}/products/count?${params}`); },
  async product(id: number): Promise<ProductDetail> { return request<ProductDetail>(`${API}/products/${id}`); },
  async deleteProducts(ids: number[]): Promise<{deleted:number}> { return request<{deleted:number}>(`${API}/products`, { method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify(ids) }); },
  async logs(): Promise<ServiceLog[]> { return request<ServiceLog[]>(`${API}/logs`); },
  async upload(file: File): Promise<Meta> { const form = new FormData(); form.append('file', file); return request<Meta>(`${API}/import`, { method:'POST', body: form }); },
  exportUrl(kind: 'csv'|'xlsx', params: URLSearchParams) { return `${API}/export.${kind}?${params}`; }
};
