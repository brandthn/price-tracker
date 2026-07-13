// Types miroir des schémas Pydantic backend (`backend/pricetracker_api/schemas/`).
// Garder synchrone avec ces fichiers si l'API évolue.

export type TicketStatus =
  | "pending"
  | "processing"
  | "ocr_processing"
  | "ocr_done"
  | "ocr_failed"
  | "validated";

export type FeedbackRating = "up" | "down";

export interface Ticket {
  id: string;
  status: TicketStatus | string;
  enseigne: string | null;
  date_ticket: string | null;
  total_eur: number | null;
  ocr_confidence: number | null;
  ocr_engine: string | null;
  ocr_model: string | null;
  ocr_duration_ms: number | null;
  ocr_error: string | null;
  ocr_attempts: number;
  last_feedback: FeedbackRating | null;
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

export interface FeedbackResponse {
  ticket: TicketDetail;
  retry_triggered: boolean;
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

export interface TicketImageURLResponse {
  read_url: string;
  expires_at: string;
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
  catalog: boolean;
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
}

export interface RankingItem {
  ean: string | null;
  produit_nom: string | null;
  brand: string | null;
  image_url: string | null;
  in_catalog: boolean;
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

export interface MapDepartementValue {
  departement: string;
  inflation_pct: number | null;
  sample_size: number | null;
}

export interface MapOut {
  period: string | null;
  values: MapDepartementValue[];
}

export interface PricePoint {
  week: string;
  median_price_eur: number;
  observations: number;
}

export interface StorePrice {
  enseigne: string;
  median_price_eur: number;
  observations: number;
  last_seen_week: string | null;
}

export interface ProductPrices {
  ean: string;
  series: PricePoint[];
  by_store: StorePrice[];
  latest_median_eur: number | null;
  pct_change_window: number | null;
}

export interface BasketMonth {
  month: string;
  total_eur: number;
  tickets: number;
}

export interface BasketProduct {
  ean: string | null;
  label: string;
  purchases: number;
  avg_price_eur: number | null;
  last_purchased: string | null;
}

export interface BasketSummary {
  tickets_count: number;
  total_spent_eur: number | null;
  avg_ticket_eur: number | null;
  first_ticket_date: string | null;
  monthly: BasketMonth[];
  top_products: BasketProduct[];
}

// Comparateur d'enseignes — indice de cherté relative (matched-basket).
export interface EnseigneSummary {
  enseigne: string;
  // null = couverture insuffisante (< min_matched produits comparables).
  cherte_index: number | null;
  matched_products: number;
  observations: number | null;
}

export interface EnseignesOut {
  window_weeks: number;
  min_matched: number;
  reference_index: number;
  items: EnseigneSummary[];
}

export interface EnseigneProductRank {
  ean: string | null;
  produit_nom: string | null;
  brand: string | null;
  image_url: string | null;
  in_catalog: boolean;
  price_eur: number | null;
  ref_price_eur: number | null;
  // Écart au prix de référence, en %. −12.0 = 12 % moins cher que la médiane.
  delta_pct: number;
}

export interface EnseigneDetailOut {
  enseigne: string;
  tracked: boolean;
  cherte_index: number | null;
  matched_products: number;
  observations: number | null;
  window_weeks: number;
  min_matched: number;
  cheaper: EnseigneProductRank[];
  dearer: EnseigneProductRank[];
}

// Reco « substitut moins cher » — /me/recommendations
export interface RecoProductRef {
  ean: string;
  name: string | null;
  brand: string | null;
  image_url: string | null;
  // €/unité (jamais le prix paquet)
  price_per_unit: number;
}

export interface RecommendationItem {
  source: RecoProductRef;
  target: RecoProductRef;
  unit: string;
  tier: number;
  score: number;
  saving_per_unit: number;
  // Pourcentage d'économie, ex: 18.4 = 18,4 % moins cher
  saving_pct: number;
  monthly_packs: number;
  monthly_saving_eur: number;
}

export interface RecommendationsOut {
  items: RecommendationItem[];
  total_monthly_saving_eur: number;
  count: number;
}