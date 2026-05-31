"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";
import {
  getTicket,
  requestUploadURL,
  uploadToSignedURL,
} from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/client";

type Stage =
  | "idle"
  | "signing"
  | "uploading"
  | "polling"
  | "done"
  | "failed";

const POLL_INTERVAL_MS = 5000;
const POLL_MAX_ATTEMPTS = 60; // 5 min max

export function UploadForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState<string | null>(null);
  const dragRef = useRef<HTMLLabelElement>(null);

  const handleFile = (f: File | null) => {
    setError(null);
    if (!f) return setFile(null);
    if (!["image/jpeg", "image/png"].includes(f.type)) {
      setError(`Format non supporté (${f.type}). JPEG ou PNG uniquement.`);
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError(`Image trop grosse (${(f.size / 1024 / 1024).toFixed(1)} MB > 10 MB).`);
      return;
    }
    setFile(f);
  };

  const handleSubmit = useCallback(async () => {
    if (!file) return;
    setError(null);
    setStage("signing");

    try {
      const contentType = file.type as "image/jpeg" | "image/png";
      const signed = await requestUploadURL(contentType);

      setStage("uploading");
      await uploadToSignedURL(signed.upload_url, file, contentType);

      setStage("polling");
      toast.success("Ticket reçu — analyse en cours…");

      // Polling jusqu'à status !== pending|processing
      let attempts = 0;
      const tick = async () => {
        attempts += 1;
        try {
          const t = await getTicket(signed.ticket_id);
          if (
            t.status === "ocr_done" ||
            t.status === "ocr_failed" ||
            t.status === "validated"
          ) {
            setStage(t.status === "ocr_failed" ? "failed" : "done");
            if (t.status === "ocr_failed") {
              toast.error("L'analyse a échoué — réessaie avec une autre photo.");
            } else {
              toast.success("Ticket analysé !");
              router.push(`/tickets/${signed.ticket_id}`);
            }
            return;
          }
          if (attempts >= POLL_MAX_ATTEMPTS) {
            setStage("failed");
            setError(
              "L'analyse prend plus de temps que prévu. Tu peux retrouver ton ticket dans la liste « Mes tickets »."
            );
            return;
          }
          setTimeout(tick, POLL_INTERVAL_MS);
        } catch {
          setStage("failed");
          setError("Une erreur est survenue pendant l'analyse. Réessaie dans un instant.");
        }
      };
      setTimeout(tick, POLL_INTERVAL_MS);
    } catch (err) {
      setStage("failed");
      if (err instanceof ApiError) {
        setError(`Erreur ${err.status} — ${err.detail ?? "réessaie dans un instant."}`);
      } else {
        setError("Impossible de joindre le serveur. Vérifie ta connexion.");
      }
    }
  }, [file, router]);

  const disabled = stage === "signing" || stage === "uploading" || stage === "polling";

  return (
    <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
      <label
        ref={dragRef}
        htmlFor="ticket-file"
        onDragOver={(e) => {
          e.preventDefault();
          dragRef.current?.classList.add("border-primary", "bg-primary/5");
        }}
        onDragLeave={() => {
          dragRef.current?.classList.remove("border-primary", "bg-primary/5");
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragRef.current?.classList.remove("border-primary", "bg-primary/5");
          handleFile(e.dataTransfer.files[0] ?? null);
        }}
        className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-stroke px-6 py-10 text-center transition-colors hover:border-primary dark:border-dark-3"
      >
        <input
          id="ticket-file"
          type="file"
          accept="image/jpeg,image/png"
          className="sr-only"
          disabled={disabled}
          onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
        />
        {file ? (
          <>
            <span className="text-base font-medium text-dark dark:text-white">
              {file.name}
            </span>
            <span className="text-xs text-dark-6">
              {(file.size / 1024).toFixed(0)} KB · {file.type}
            </span>
            <span className="mt-2 text-xs text-primary">
              Cliquer pour changer d&apos;image
            </span>
          </>
        ) : (
          <>
            <span className="text-base font-medium text-dark dark:text-white">
              Cliquer ou glisser une image ici
            </span>
            <span className="text-xs text-dark-6">
              JPEG ou PNG, max 10 MB
            </span>
          </>
        )}
      </label>

      {error && (
        <div className="mt-4 rounded-lg border border-red-light bg-red-light-5 p-3 text-sm text-red dark:border-red-dark dark:bg-red/10">
          ⚠️ {error}
        </div>
      )}

      <div className="mt-6 flex flex-col gap-3">
        <button
          type="button"
          disabled={!file || disabled}
          onClick={handleSubmit}
          className="rounded-lg bg-primary px-5 py-3 font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {labelForStage(stage)}
        </button>

        {stage === "polling" && (
          <p className="text-xs text-dark-6">
            Cela prend généralement quelques secondes.
          </p>
        )}
      </div>

      <Steps stage={stage} />
    </div>
  );
}

function labelForStage(stage: Stage): string {
  switch (stage) {
    case "idle":
      return "Envoyer mon ticket";
    case "signing":
      return "Préparation…";
    case "uploading":
      return "Envoi de l'image…";
    case "polling":
      return "Analyse en cours…";
    case "done":
      return "Terminé ✓";
    case "failed":
      return "Réessayer";
  }
}

const STEPS: { key: Stage; label: string }[] = [
  { key: "signing", label: "Préparation" },
  { key: "uploading", label: "Envoi de l'image" },
  { key: "polling", label: "Analyse de ton ticket" },
  { key: "done", label: "Prêt à valider" },
];

function Steps({ stage }: { stage: Stage }) {
  if (stage === "idle") return null;
  const order: Stage[] = ["signing", "uploading", "polling", "done"];
  const currentIdx = order.indexOf(stage);

  return (
    <ol className="mt-6 flex flex-col gap-3 border-t border-stroke pt-6 text-sm dark:border-dark-3">
      {STEPS.map((step, idx) => {
        const isDone = idx < currentIdx || stage === "done";
        const isActive = idx === currentIdx && stage !== "done";
        return (
          <li key={step.key} className="flex items-center gap-3">
            <span
              className={`grid size-6 place-items-center rounded-full text-xs font-bold ${
                isDone
                  ? "bg-green text-white"
                  : isActive
                  ? "bg-primary text-white"
                  : "bg-gray-2 text-dark-6 dark:bg-dark-3"
              }`}
            >
              {isDone ? "✓" : idx + 1}
            </span>
            <span
              className={
                isDone || isActive
                  ? "text-dark dark:text-white"
                  : "text-dark-6"
              }
            >
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
