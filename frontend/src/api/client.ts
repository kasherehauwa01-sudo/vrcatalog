import { codeRequest } from "../catalogQuery";
import type { CategoryNode } from "../categoryTree";
import type {
  Meta,
  Product,
  ProductPage,
  ProductDetail,
  ServiceLog,
  Notification,
  Warehouse,
  ProductType,
  XmlServerSetting,
  AutoImportState,
  MailSetting,
  NotificationScenario,
  ScenarioRun,
  ScenarioSummary,
  NotificationHistory,
  DynamicAnalog,
  AnalogSelectionSetting,
  PhotoReportPage,
  ProductHistoryDetail,
  ProductHistoryPreview,
  ProductHistorySetting,
  ProductHistorySummary,
} from "../types/catalog";

const basePath = import.meta.env.BASE_URL.replace(/\/$/, "");
const API = `${basePath}/api`;
let csrfToken = "";
let adminOperations = Promise.resolve();

// Session checks rotate the token on the server, so keep them ordered with admin writes.
function runAdminOperation<T>(operation: () => Promise<T>): Promise<T> {
  const result = adminOperations.then(operation);
  adminOperations = result.then(() => {}, () => {});
  return result;
}

function expireAdminSession(): void {
  csrfToken = "";
  window.dispatchEvent(new Event("vrcatalog-admin-expired"));
}

async function fetchResponse(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, { ...init, credentials: "same-origin" });
  if (!response.ok) {
    if (response.status === 401 && !url.endsWith("/admin/login")) expireAdminSession();
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Ошибка API: ${response.status}`);
  }
  return response;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchResponse(url, init);
  return response.json() as Promise<T>;
}

async function refreshAdminSession(): Promise<void> {
  csrfToken = "";
  const result = await request<{ authenticated: boolean; csrf_token: string }>(
    `${API}/admin/session`, { cache: "no-store" },
  );
  if (!result.authenticated || !result.csrf_token) {
    expireAdminSession();
    throw new Error("Требуется вход администратора");
  }
  csrfToken = result.csrf_token;
}

async function fetchAdminResponse(url: string, init: RequestInit, refreshSession = false): Promise<Response> {
  if (refreshSession || !csrfToken) await refreshAdminSession();
  const headers = new Headers(init.headers);
  headers.set("X-CSRF-Token", csrfToken);
  return fetchResponse(url, { ...init, headers });
}

async function adminRequest<T>(url: string, init: RequestInit, refreshSession = false): Promise<T> {
  const response = await runAdminOperation(() => fetchAdminResponse(url, init, refreshSession));
  return response.json() as Promise<T>;
}

export type AccessDevice = {
  id: number;
  name: string;
  owner: string;
  comment: string;
  fingerprint: string;
  common_name: string;
  expires_at: string;
  last_seen_at: string | null;
  status: "active" | "revoked" | "expired" | "pending";
  replaces_id: number | null;
  awaiting_activation: boolean;
  crl_pending: boolean;
};
export type DeviceDetails = Pick<AccessDevice, "name" | "owner" | "comment">;
export type DevicePackage = { device: AccessDevice; password: string; file: Blob; filename: string };

export const api = {
  accessDevices(): Promise<AccessDevice[]> {
    return request(`${API}/access/devices`, { cache: "no-store" });
  },
  saveAccessDevice(action: string, data?: DeviceDetails, method = "POST"): Promise<AccessDevice> {
    return adminRequest(`${API}/access/devices/${action}`, {
      method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
  },
  async downloadDevicePackage(action: string, data: { operation_id: string } & Partial<DeviceDetails>): Promise<DevicePackage> {
    const response = await runAdminOperation(() => fetchAdminResponse(`${API}/access/devices/${action}`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    }));
    if (response.headers.get("Content-Type")?.split(";")[0] !== "application/json") {
      throw new Error("Ответ выпуска не подтверждён. Проверьте список устройств перед новой операцией.");
    }
    const result = await response.json();
    if (typeof result.password !== "string" || !/^[A-Za-z0-9]{32}$/.test(result.password)
        || typeof result.pkcs12_base64 !== "string" || !result.device?.id
        || typeof result.filename !== "string" || !/^device-[a-f0-9]+\.p12$/.test(result.filename)) {
      throw new Error("Ответ выпуска не подтверждён. Проверьте список устройств перед новой операцией.");
    }
    let bytes: Uint8Array<ArrayBuffer>;
    try { bytes = Uint8Array.from(atob(result.pkcs12_base64), (value) => value.charCodeAt(0)); }
    catch { throw new Error("Файл не получен. Проверьте список устройств перед новой операцией."); }
    if (!bytes.length) throw new Error("Файл не получен. Проверьте список устройств перед новой операцией.");
    return { device: result.device, password: result.password, filename: result.filename,
      file: new Blob([bytes], { type: "application/x-pkcs12" }) };
  },
  async adminLogin(password: string): Promise<void> {
    await runAdminOperation(async () => {
      const result = await request<{ authenticated: boolean; csrf_token: string }>(`${API}/admin/login`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }),
      });
      csrfToken = result.csrf_token;
    });
  },
  async adminSession(): Promise<boolean> {
    try {
      await runAdminOperation(refreshAdminSession);
      return true;
    } catch {
      return false;
    }
  },
  async adminLogout(): Promise<void> {
    await runAdminOperation(async () => {
      await fetchAdminResponse(`${API}/admin/logout`, { method: "POST" });
      csrfToken = "";
    });
  },
  async meta(): Promise<Meta> {
    return request<Meta>(`${API}/meta`);
  },
  async categoryTree(): Promise<CategoryNode[]> {
    return request(`${API}/filters/sections`);
  },
  async folders(): Promise<string[]> {
    return request<string[]>(`${API}/filters/folders`);
  },
  async categoryStatus(): Promise<CategorySyncStatus> { return request(`${API}/catalog-categories/status`); },
  async syncCategories(): Promise<CategorySyncStatus> { return adminRequest(`${API}/catalog-categories/sync`, { method: "POST" }); },
  async filters(params?: URLSearchParams): Promise<Record<string, string[]>> {
    const query = params?.toString();
    return request<Record<string, string[]>>(`${API}/filters${query ? `?${query}` : ""}`);
  },
  async products(params: URLSearchParams): Promise<Product[]> {
    return request<Product[]>(`${API}/products?${params}`);
  },
  async searchProducts(params: URLSearchParams): Promise<ProductPage> {
    const { query, init } = codeRequest(params);
    return request<ProductPage>(`${API}/products/search?${query}`, init);
  },
  async productCount(params: URLSearchParams): Promise<{ count: number }> {
    return request<{ count: number }>(`${API}/products/count?${params}`);
  },
  async product(id: number): Promise<ProductDetail> {
    return request<ProductDetail>(`${API}/products/${id}`);
  },
  async photoReport(params: URLSearchParams): Promise<PhotoReportPage> {
    const { query, init } = codeRequest(params);
    return request<PhotoReportPage>(`${API}/reports/photos?${query}`, init);
  },
  async productHistorySettings(): Promise<ProductHistorySetting> {
    return request<ProductHistorySetting>(`${API}/history/monthly-promotion/settings`);
  },
  async updateProductHistorySettings(payload: ProductHistorySetting): Promise<ProductHistorySetting> {
    return adminRequest<ProductHistorySetting>(`${API}/history/monthly-promotion/settings`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
  },
  async productHistoryPreview(period?: string): Promise<ProductHistoryPreview> {
    const query = period ? `?period=${encodeURIComponent(period)}` : "";
    return request<ProductHistoryPreview>(`${API}/history/monthly-promotion/preview${query}`);
  },
  async createProductHistory(period: string): Promise<ProductHistorySummary> {
    return adminRequest<ProductHistorySummary>(`${API}/history/monthly-promotion?period=${encodeURIComponent(period)}`, { method: "POST" });
  },
  async productHistory(): Promise<ProductHistorySummary[]> {
    return request<ProductHistorySummary[]>(`${API}/history/monthly-promotion`);
  },
  async productHistoryDetail(period: string, search = ""): Promise<ProductHistoryDetail> {
    const query = search ? `?search=${encodeURIComponent(search)}` : "";
    return request<ProductHistoryDetail>(`${API}/history/monthly-promotion/${encodeURIComponent(period.slice(0, 7))}${query}`);
  },
  async downloadReportPhotos(images: { product_id: number; image_id: number }[]): Promise<Blob> {
    const response = await runAdminOperation(() => fetchAdminResponse(`${API}/reports/photos/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ images }),
    }));
    return response.blob();
  },
  async productAnalogs(id: number, showAll = false): Promise<DynamicAnalog[]> {
    return request<DynamicAnalog[]>(`${API}/products/${id}/dynamic-analogs${showAll ? "?show_all=true" : ""}`);
  },
  async analogSelectionSettings(): Promise<AnalogSelectionSetting> {
    return request<AnalogSelectionSetting>(`${API}/analog-selection-settings`);
  },
  async updateAnalogSelectionSettings(payload: AnalogSelectionSetting): Promise<AnalogSelectionSetting> {
    return adminRequest<AnalogSelectionSetting>(`${API}/analog-selection-settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async deleteProducts(ids: number[]): Promise<{ deleted: number }> {
    return adminRequest<{ deleted: number }>(`${API}/products`, {
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
    return adminRequest<Warehouse>(`${API}/warehouses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async updateWarehouse(
    id: number,
    payload: { code: string; name: string },
  ): Promise<Warehouse> {
    return adminRequest<Warehouse>(`${API}/warehouses/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async deleteWarehouse(id: number): Promise<{ deleted: boolean }> {
    return adminRequest<{ deleted: boolean }>(`${API}/warehouses/${id}`, {
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
    return adminRequest<ProductType>(`${API}/product-types`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async updateProductType(
    id: number,
    payload: { code: string; name: string },
  ): Promise<ProductType> {
    return adminRequest<ProductType>(`${API}/product-types/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async deleteProductType(id: number): Promise<{ deleted: boolean }> {
    return adminRequest<{ deleted: boolean }>(`${API}/product-types/${id}`, {
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
    password?: string;
    xml_dir: string;
  }): Promise<XmlServerSetting> {
    return adminRequest<XmlServerSetting>(`${API}/xml-server-settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  async testXmlServerSettings(): Promise<{ success: boolean; message: string }> {
    return adminRequest<{ success: boolean; message: string }>(`${API}/xml-server-settings/test`, {
      method: "POST",
    });
  },
  async autoImportState(): Promise<AutoImportState> {
    return request<AutoImportState>(`${API}/auto-import-state`);
  },
  async runAutoImportNow(): Promise<{ started: boolean }> {
    return adminRequest<{ started: boolean }>(`${API}/auto-import/run`, {
      method: "POST",
    });
  },
  async mailSettings(): Promise<MailSetting> {
    return request<MailSetting>(`${API}/mail-settings`);
  },
  async updateMailSettings(payload: MailSetting): Promise<MailSetting> {
    return adminRequest<MailSetting>(`${API}/mail-settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  },
  async sendTestMail(email: string): Promise<{ success: boolean; message: string }> {
    return adminRequest<{ success: boolean; message: string }>(`${API}/mail-settings/test`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
  },
  async unneededFolderScenario(): Promise<NotificationScenario> {
    return request<NotificationScenario>(`${API}/notification-scenarios/unneeded-folder`);
  },
  async updateUnneededFolderScenario(payload: NotificationScenario): Promise<NotificationScenario> {
    return adminRequest<NotificationScenario>(`${API}/notification-scenarios/unneeded-folder`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  },
  async monthlyPromotionScenario(): Promise<NotificationScenario> {
    return request<NotificationScenario>(`${API}/notification-scenarios/monthly-promotion`);
  },
  async notificationScenarios(): Promise<ScenarioSummary[]> {
    return request<ScenarioSummary[]>(`${API}/notification-scenarios`);
  },
  async toggleNotificationScenario(code: string, enabled: boolean): Promise<ScenarioSummary> {
    return adminRequest<ScenarioSummary>(`${API}/notification-scenarios/${code}/enabled`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
  },
  async notificationHistory(code: string, search = "", status = "all"): Promise<NotificationHistory[]> {
    const params = new URLSearchParams({ search, status });
    return request<NotificationHistory[]>(`${API}/notification-scenarios/${code}/history?${params}`);
  },
  async updateMonthlyPromotionScenario(payload: NotificationScenario): Promise<NotificationScenario> {
    return adminRequest<NotificationScenario>(`${API}/notification-scenarios/monthly-promotion`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  },
  async runMonthlyPromotion(): Promise<ScenarioRun> {
    return adminRequest<ScenarioRun>(`${API}/notification-scenarios/monthly-promotion/run`, { method: "POST" });
  },
  async previewMonthlyPromotion(): Promise<ScenarioRun> {
    return request<ScenarioRun>(`${API}/notification-scenarios/monthly-promotion/preview`);
  },
  async upload(file: File): Promise<Meta> {
    const form = new FormData();
    form.append("file", file);
    return adminRequest<Meta>(`${API}/import`, { method: "POST", body: form });
  },
  exportUrl(kind: "csv" | "xlsx", params: URLSearchParams) {
    return `${API}/export.${kind}?${params}`;
  },
  async startExcelExport(params: URLSearchParams, selectedIds: readonly number[] = []): Promise<{ job_id: string; status: string }> {
    if (selectedIds.length) {
      const query = new URLSearchParams();
      ["group_categories", "group_folders", "promotion", "promotion_type", "order_form", "zip_categories", "adjustment", "adjustment_percent"].forEach((key) => {
        if (params.has(key)) query.set(key, params.get(key)!);
      });
      params.getAll("column").forEach((column) => query.append("column", column));
      return request<{ job_id: string; status: string }>(`${API}/exports/xlsx?${query}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_ids: selectedIds }),
      });
    }
    const { query, init } = codeRequest(params);
    return request<{ job_id: string; status: string }>(`${API}/exports/xlsx?${query}`, init ?? { method: "POST" });
  },
  async excelExportStatus(jobId: string): Promise<{ status: "processing" | "ready" | "error"; error?: string; size?: number; filename?: string; media_type?: string; processed: number; total?: number; progress: number }> {
    return request<{ status: "processing" | "ready" | "error"; error?: string; size?: number; filename?: string; media_type?: string; processed: number; total?: number; progress: number }>(`${API}/exports/xlsx/${jobId}`);
  },
  async excelExportChunk(jobId: string, offset: number): Promise<{ content: ArrayBuffer; nextOffset: number; size: number }> {
    const response = await fetch(`${API}/exports/xlsx/${jobId}/chunk?offset=${offset}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? `Ошибка скачивания: ${response.status}`);
    }
    return {
      content: await response.arrayBuffer(),
      nextOffset: Number(response.headers.get("X-Next-Offset")),
      size: Number(response.headers.get("X-File-Size")),
    };
  },
};

export type CategorySyncStatus = { status: string; last_attempt_at?: string; last_success_at?: string;
  category_count?: number; section_count?: number; last_error?: string;
  unmatched_sections: { name: string; product_count: number }[] };
