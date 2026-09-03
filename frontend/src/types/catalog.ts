export type Product = {
  id: number;
  code: string;
  name: string;
  article?: string;
  section?: string;
  product_type?: string;
  product_type_name?: string;
  quantity: number;
  is_new: boolean;
  images: { order: number; url: string }[];
  retail_price?: number;
  prices: { price_type: string; value: number }[];
};
export type ProductPage = {
  items: Product[];
  pagination: {
    page: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
  };
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

export type DynamicAnalog = {
  id: number;
  code: string;
  article?: string;
  name: string;
  similarity: number;
  retail_price?: number;
  image_url?: string;
  matched: AnalogCharacteristicComparison[];
  unmatched: AnalogCharacteristicComparison[];
};

export type AnalogCharacteristicComparison = {
  name: string;
  original_value: string;
  analog_value: string;
};

export type AnalogSelectionSetting = {
  primary_properties: string[];
  minimum_similarity: number;
  maximum_analogs: number;
  available_properties: string[];
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
  connection_attempts: number;
  retry_delay_seconds: number;
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

export type MailSetting = {
  smtp_host: string;
  smtp_port: number;
  encryption: "none" | "starttls" | "ssl";
  username: string;
  password?: string;
  password_configured: boolean;
  sender_name: string;
  sender_email: string;
  connection_status: string;
  last_success_at?: string;
  last_sent_at?: string;
  last_error?: string;
};

export type NotificationScenario = {
  code: string;
  enabled: boolean;
  send_time: string;
  recipients: string[];
};

export type ScenarioRun = {
  status: string;
  changes: number;
  sent: number;
  recipients: string[];
  html: string;
  error?: string;
};

export type ScenarioSummary = { code: string; name: string; enabled: boolean };
export type NotificationHistory = {
  id: number;
  scenario_code: string;
  sent_at: string;
  recipients: string[];
  subject: string;
  body_html: string;
  status: "sent" | "error";
  error_message?: string;
  duration_ms: number;
};
