import { apiFetch } from "./client";
import type {
  FeedbackRating,
  FeedbackResponse,
  Ticket,
  TicketDetail,
  TicketImageURLResponse,
  TicketItemPatch,
  TicketsListResponse,
  UploadURLResponse,
} from "./types";

export function requestUploadURL(
  contentType: "image/jpeg" | "image/png" = "image/jpeg",
): Promise<UploadURLResponse> {
  return apiFetch<UploadURLResponse>("/tickets/upload-url", {
    method: "POST",
    body: { content_type: contentType },
    authenticated: true,
  });
}

export function listTickets(
  limit = 20,
  offset = 0,
): Promise<TicketsListResponse> {
  return apiFetch<TicketsListResponse>(
    `/tickets?limit=${limit}&offset=${offset}`,
    { authenticated: true },
  );
}

export function getTicket(id: string): Promise<TicketDetail> {
  return apiFetch<TicketDetail>(`/tickets/${id}`, { authenticated: true });
}

export function getTicketImageURL(
  id: string,
): Promise<TicketImageURLResponse> {
  return apiFetch<TicketImageURLResponse>(`/tickets/${id}/image-url`, {
    authenticated: true,
  });
}

export function patchTicketItems(
  id: string,
  items: TicketItemPatch[],
): Promise<TicketDetail> {
  return apiFetch<TicketDetail>(`/tickets/${id}/items`, {
    method: "PATCH",
    body: { items },
    authenticated: true,
  });
}

// un rating negatif relance un OCR tier-2 côté backend
export function submitFeedback(
  id: string,
  rating: FeedbackRating,
): Promise<FeedbackResponse> {
  return apiFetch<FeedbackResponse>(`/tickets/${id}/feedback`, {
    method: "POST",
    body: { rating },
    authenticated: true,
  });
}

// signed url v4: le Content-Type doit matcher celui signé, sinon 403
export async function uploadToSignedURL(
  signedUrl: string,
  file: File,
  contentType: "image/jpeg" | "image/png",
): Promise<void> {
  const res = await fetch(signedUrl, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: file,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Upload GCS échoué (HTTP ${res.status}) — ${text}`);
  }
}

export type {
  FeedbackResponse,
  Ticket,
  TicketDetail,
  TicketsListResponse,
  UploadURLResponse,
};
