// Types miroir des schémas Pydantic backend (`backend/pricetracker_api/schemas/`).
// Garder synchrone avec ces fichiers si l'API évolue.

export type TicketStatus =
  | "pending"
  | "processing"
  | "ocr_done"
  | "ocr_failed"
  | "validated";

export interface Ticket {
  id: string;
  status: TicketStatus | string;
  enseigne: string | null;
  date_ticket: string | null;
  total_eur: number | null;
  ocr_confidence: number | null;
  ocr_engine: string | null;
  ocr_duration_ms: number | null;
  ocr_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrixExtrait {
  id: string;
  line_index: number;
  raw_text: string;
  ean: string | null;
  produit_nom: string | null;
  quantity: number | null;
  unit_price: number | null;
  line_total: number | null;
  price_eur: number | null;
  match_method: string | null;
  ocr_confidence: number | null;
  match_confidence: number | null;
  needs_validation: boolean;
  validated_by_user: boolean;
}

export interface TicketDetail extends Ticket {
  items: PrixExtrait[];
}

export interface TicketsListResponse {
  items: Ticket[];
  total: number;
  limit: number;
  offset: number;
}

export interface UploadURLResponse {
  ticket_id: string;
  upload_url: string;
  gcs_path: string;
  expires_at: string;
  content_type: "image/jpeg" | "image/png";
}

export interface TicketItemPatch {
  id: string;
  ean?: string | null;
  produit_nom?: string | null;
  quantity?: number | null;
  price_eur?: number | null;
}

export interface Product {
  ean: string;
  name: string | null;
  brand: string | null;
  category_l1: string | null;
  category_l2: string | null;
  category_l3: string | null;
  nutriscore: string | null;
  nova: number | null;
  ecoscore: string | null;
  image_url: string | null;
  off_found: boolean;
  source: string | null;
}

export interface Substitute extends Product {
  similarity: number;
}

export interface ProductSearchResult {
  items: Product[];
  total: number;
}

export interface IndexPoint {
  date: string;
  value: number;
  sample_size: number | null;
}

export interface InflationIndex {
  scope: string;
  base_period: string | null;
  current: number | null;
  series: IndexPoint[];
  insee_comparison: number | null;
}

export interface RankingItem {
  ean: string | null;
  produit_nom: string | null;
  brand: string | null;
  pct_change: number;
  price_eur_current: number | null;
  price_eur_previous: number | null;
  sample_size: number | null;
}

export interface RankingsOut {
  period: string | null;
  items: RankingItem[];
}

export interface BrandStats {
  brand: string;
  product_count: number;
  avg_price_eur: number | null;
  median_pct_change: number | null;
  top_increases: RankingItem[];
}
