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

// Signed URL de lecture (GET) de l'image du ticket, pour l'afficher côté UI.
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

// Boucle de feedback : 👍/👎 sur l'output OCR. Un 👎 déclenche un re-OCR tier-2.
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

// Upload direct GCS via Signed URL V4. Doit matcher `Content-Type` exactement.
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
