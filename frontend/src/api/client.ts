import type { Meta, Product, ProductDetail } from '../types/catalog';
const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api';
export const api = {
  async meta(): Promise<Meta> { return fetch(`${API}/meta`).then(r => r.json()); },
  async filters(): Promise<Record<string,string[]>> { return fetch(`${API}/filters`).then(r => r.json()); },
  async products(params: URLSearchParams): Promise<Product[]> { return fetch(`${API}/products?${params}`).then(r => r.json()); },
  async product(id: number): Promise<ProductDetail> { return fetch(`${API}/products/${id}`).then(r => r.json()); },
  async upload(file: File): Promise<Meta> { const form = new FormData(); form.append('file', file); return fetch(`${API}/import`, { method:'POST', body: form }).then(r => r.json()); },
  exportUrl(kind: 'csv'|'xlsx', search: string) { return `${API}/export.${kind}?search=${encodeURIComponent(search)}`; }
};
