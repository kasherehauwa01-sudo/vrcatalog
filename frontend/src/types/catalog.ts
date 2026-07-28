export type Product = {
  id: number;
  code: string;
  name: string;
  article?: string;
  section?: string;
  product_type?: string;
  product_type_name?: string;
  quantity: number;
  images: { order: number; url: string }[];
  retail_price?: number;
  prices: { price_type: string; value: number }[];
};
export type ProductDetail = Product & {
  created_at: string;
  updated_at: string;
  description?: string;
  manufacturer?: string;
  brand?: string;
  manager?: string;
  country?: string;
  material?: string;
  color?: string;
  certificate?: string;
  tags?: string;
  prices: { price_type: string; value: number }[];
  stocks: { warehouse: string; warehouse_name?: string; quantity: number }[];
  properties: { property_code?: string; name: string; value?: string }[];
  analogs: { code?: string; name?: string }[];
  barcodes: { value: string }[];
};
export type Meta = {
  last_import?: string;
  product_count: number;
  import_status?: string;
  imported_count?: number;
  errors?: string;
};
export type ServiceLog = {
  id: number;
  level: string;
  event: string;
  message: string;
  error_type?: string;
  traceback?: string;
  created_at: string;
};

export type Notification = {
  id: number;
  type: string;
  title: string;
  message: string;
  created_at: string;
  is_read: boolean;
};

export type ProductType = {
  id: number;
  code: string;
  name: string;
  created_at: string;
};

export type Warehouse = {
  id: number;
  code: string;
  name: string;
  created_at: string;
};

export type XmlServerSetting = {
  id: number;
  protocol: string;
  host: string;
  port: number;
  username: string;
  password: string;
  xml_dir: string;
  created_at: string;
  updated_at: string;
};

export type AutoImportState = {
  status: string;
  last_run_at?: string;
  processed_files: number;
  successful_files: number;
  failed_files: number;
  last_error?: string;
  is_running: boolean;
  updated_at?: string;
};
