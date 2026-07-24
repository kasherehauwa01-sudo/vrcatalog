import type {
  Meta,
  Product,
  ProductDetail,
  ServiceLog,
  Notification,
  Warehouse,
  ProductType,
  XmlServerSetting,
  AutoImportState,
} from "../types/catalog";

const basePath = import.meta.env.BASE_URL.replace(/\/$/, "");
const API = `${basePath}/api`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Ошибка API: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  async meta(): Promise<Meta> {
    return request<Meta>(`${API}/meta`);
  },
  async filters(): Promise<Record<string, string[]>> {
    return request<Record<string, string[]>>(`${API}/filters`);
  },
  async products(params: URLSearchParams): Promise<Product[]> {
    return request<Product[]>(`${API}/products?${params}`);
  },
  async productCount(params: URLSearchParams): Promise<{ count: number }> {
    return request<{ count: number }>(`${API}/products/count?${params}`);
  },
  async product(id: number): Promise<ProductDetail> {
    return request<ProductDetail>(`${API}/products/${id}`);
  },
  async deleteProducts(ids: number[]): Promise<{ deleted: number }> {
    return request<{ deleted: number }>(`${API}/products`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ids),
    });
  },
  async logs(): Promise<ServiceLog[]> {
    return request<ServiceLog[]>(`${API}/logs`);
  },
  async notifications(): Promise<Notification[]> {
    return request<Notification[]>(`${API}/notifications`);
  },
  async unreadNotifications(): Promise<{ count: number }> {
    return request<{ count: number }>(`${API}/notifications/unread-count`);
  },
  async markNotificationRead(id: number): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(`${API}/notifications/${id}/read`, {
      method: "POST",
    });
  },
  async markAllNotificationsRead(): Promise<{ updated: number }> {
    return request<{ updated: number }>(`${API}/notifications/read-all`, {
      method: "POST",
    });
  },
  async warehouses(): Promise<Warehouse[]> {
    return request<Warehouse[]>(`${API}/warehouses`);
  },
  async warehouseCodes(): Promise<{ codes: string[] }> {
    return request<{ codes: string[] }>(`${API}/warehouses/codes`);
  },
  async createWarehouse(payload: {
    code: string;
    name: string;
  }): Promise<Warehouse> {
    return request<Warehouse>(`${API}/warehouses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async updateWarehouse(
    id: number,
    payload: { code: string; name: string },
  ): Promise<Warehouse> {
    return request<Warehouse>(`${API}/warehouses/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async deleteWarehouse(id: number): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`${API}/warehouses/${id}`, {
      method: "DELETE",
    });
  },
  async productTypes(): Promise<ProductType[]> {
    return request<ProductType[]>(`${API}/product-types`);
  },
  async productTypeCodes(): Promise<{ codes: string[] }> {
    return request<{ codes: string[] }>(`${API}/product-types/codes`);
  },
  async createProductType(payload: {
    code: string;
    name: string;
  }): Promise<ProductType> {
    return request<ProductType>(`${API}/product-types`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async updateProductType(
    id: number,
    payload: { code: string; name: string },
  ): Promise<ProductType> {
    return request<ProductType>(`${API}/product-types/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async deleteProductType(id: number): Promise<{ deleted: boolean }> {
    return request<{ deleted: boolean }>(`${API}/product-types/${id}`, {
      method: "DELETE",
    });
  },
  async xmlServerSettings(): Promise<XmlServerSetting> {
    return request<XmlServerSetting>(`${API}/xml-server-settings`);
  },
  async updateXmlServerSettings(payload: {
    protocol: string;
    host: string;
    port: number;
    username: string;
    password: string;
    xml_dir: string;
  }): Promise<XmlServerSetting> {
    return request<XmlServerSetting>(`${API}/xml-server-settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async testXmlServerSettings(): Promise<{ success: boolean; message: string }> {
    return request<{ success: boolean; message: string }>(`${API}/xml-server-settings/test`, {
      method: "POST",
    });
  },
  async autoImportState(): Promise<AutoImportState> {
    return request<AutoImportState>(`${API}/auto-import-state`);
  },
  async upload(file: File): Promise<Meta> {
    const form = new FormData();
    form.append("file", file);
    return request<Meta>(`${API}/import`, { method: "POST", body: form });
  },
  exportUrl(kind: "csv" | "xlsx", params: URLSearchParams) {
    return `${API}/export.${kind}?${params}`;
  },
};
