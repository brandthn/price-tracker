"""L'assemblage : CLIP gele, le projecteur, SmolLM2 gele, et les LoRA.

Environ 457M de parametres, dont seulement une dizaine de millions sont entraines (le
projecteur et les LoRA) : CLIP ViT-B/16 pese 86M, SmolLM2-360M en pese 360.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import torch
import torch.nn as nn

from receipt_vlm.models.constrained import CanonicalJsonStateMachine, pick_token
from receipt_vlm.models.lora import inject_lora, merge_lora
from receipt_vlm.models.projector import MultimodalProjector

CLIP_MODEL = "openai/clip-vit-base-patch16"
LM_MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"

VISION_DIM = 768
LANG_DIM = 960
NUM_PATCHES = 197
NUM_VISUAL_TOKENS = 32

SYSTEM_PROMPT = (
    "Tu analyses la photo d'un ticket de caisse de supermarché français. "
    "Réponds UNIQUEMENT avec le JSON canonique du ticket."
)


class ReceiptVLM(nn.Module):
    """LLaVA-style VLM for French receipt parsing."""

    def __init__(
        self,
        lora_rank: int = 16,
        lora_alpha: float = 32.0,
        lora_dropout: float = 0.05,
        gradient_checkpointing: bool = False,
    ) -> None:
        super().__init__()
        from transformers import AutoModelForCausalLM, AutoTokenizer, CLIPVisionModel

        self.lora_rank = lora_rank
        self.lora_alpha = lora_alpha

        self.vision_encoder = CLIPVisionModel.from_pretrained(CLIP_MODEL)
        for param in self.vision_encoder.parameters():
            param.requires_grad = False

        self.projector = MultimodalProjector(
            vision_dim=VISION_DIM,
            lang_dim=LANG_DIM,
            num_patches=NUM_PATCHES,
            num_queries=NUM_VISUAL_TOKENS,
        )

        self.tokenizer = AutoTokenizer.from_pretrained(LM_MODEL)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.lm = AutoModelForCausalLM.from_pretrained(LM_MODEL)
        for param in self.lm.parameters():
            param.requires_grad = False
        if lora_rank > 0:
            inject_lora(
                self.lm,
                rank=lora_rank,
                alpha=lora_alpha,
                dropout=lora_dropout,
                target_modules=("q_proj", "v_proj"),
            )
        if gradient_checkpointing and hasattr(self.lm, "gradient_checkpointing_enable"):
            self.lm.gradient_checkpointing_enable()

        self.system_prompt = SYSTEM_PROMPT
        self._token_texts: Optional[list[str]] = None

    # Training forward

    def encode_image(self, pixel_values: torch.Tensor) -> torch.Tensor:
        """CLIP-normalized pixels ``(B, 3, 224, 224)`` → ``(B, 32, 960)``."""
        vision_out = self.vision_encoder(pixel_values=pixel_values)
        return self.projector(vision_out.last_hidden_state)

    def forward(
        self,
        pixel_values: torch.Tensor,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
        labels: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Teacher-forced forward pass."""
        visual_tokens = self.encode_image(pixel_values)  # (B, 32, 960)
        text_embeds = self.lm.get_input_embeddings()(input_ids)
        combined = torch.cat([visual_tokens, text_embeds], dim=1)

        batch, prefix = visual_tokens.shape[0], visual_tokens.shape[1]
        if attention_mask is None:
            attention_mask = torch.ones_like(input_ids)
        full_mask = torch.cat(
            [attention_mask.new_ones(batch, prefix), attention_mask], dim=1
        )

        logits = self.lm(inputs_embeds=combined, attention_mask=full_mask).logits

        loss = None
        if labels is not None:
            full_labels = torch.cat(
                [labels.new_full((batch, prefix), -100), labels], dim=1
            )
            shift_logits = logits[:, :-1, :].contiguous()
            shift_labels = full_labels[:, 1:].contiguous()
            loss = nn.functional.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                ignore_index=-100,
            )
        return logits, loss

    # Inference

    def _vocab_texts(self) -> list[str]:
        if self._token_texts is None:
            vocab_size = self.lm.get_input_embeddings().weight.shape[0]
            self._token_texts = [
                self.tokenizer.decode([i]) for i in range(vocab_size)
            ]
        return self._token_texts

    def _prompt_embeds(self, batch: int, device: torch.device) -> torch.Tensor:
        prompt_ids = self.tokenizer(
            self.system_prompt, return_tensors="pt", add_special_tokens=False
        ).input_ids.to(device)
        embeds = self.lm.get_input_embeddings()(prompt_ids)
        return embeds.expand(batch, -1, -1)

    @torch.no_grad()
    def generate(
        self,
        pixel_values: torch.Tensor,
        max_new_tokens: int = 768,
        constrained: bool = True,
        top_k: int = 64,
    ) -> list[str]:
        """Genere le JSON canonique pour un batch d'images.

        Avec le decodage contraint (par defaut), la sortie est valide par construction :
        le masque de tokens interdit mecaniquement tout ce qui casserait la grammaire. En
        contrepartie il tourne echantillon par echantillon, donc le batch est traite en
        sequentiel.
        """
        if not constrained:
            return self._generate_free(pixel_values, max_new_tokens)
        return [
            self._generate_constrained(pixel_values[i : i + 1], max_new_tokens, top_k)
            for i in range(pixel_values.shape[0])
        ]

    def _generate_free(self, pixel_values: torch.Tensor, max_new_tokens: int) -> list[str]:
        device = pixel_values.device
        visual_tokens = self.encode_image(pixel_values)
        prompt_embeds = self._prompt_embeds(pixel_values.shape[0], device)
        combined = torch.cat([visual_tokens, prompt_embeds], dim=1)
        output_ids = self.lm.generate(
            inputs_embeds=combined,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id,
        )
        return [
            self.tokenizer.decode(ids, skip_special_tokens=True)
            for ids in output_ids
        ]

    def _generate_constrained(
        self, pixel_values: torch.Tensor, max_new_tokens: int, top_k: int
    ) -> str:
        device = pixel_values.device
        token_texts = self._vocab_texts()
        machine = CanonicalJsonStateMachine()

        visual_tokens = self.encode_image(pixel_values)
        prompt_embeds = self._prompt_embeds(1, device)
        combined = torch.cat([visual_tokens, prompt_embeds], dim=1)

        out = self.lm(inputs_embeds=combined, use_cache=True)
        past = out.past_key_values
        logits = out.logits[0, -1, :]

        pieces: list[str] = []
        steps = 0
        while not machine.is_complete() and steps < max_new_tokens:
            token_id, text = pick_token(logits, machine, token_texts, top_k=top_k)
            pieces.append(text)
            if token_id is not None:
                next_ids = torch.tensor([[token_id]], device=device)
            else:
                # Continuation forcee : on re-encode le texte et on le rejoue.
                forced = self.tokenizer(
                    text, return_tensors="pt", add_special_tokens=False
                ).input_ids.to(device)
                next_ids = forced
            out = self.lm(input_ids=next_ids, past_key_values=past, use_cache=True)
            past = out.past_key_values
            logits = out.logits[0, -1, :]
            steps += next_ids.shape[1]

        if not machine.is_complete():
            # Budget epuise : on ferme le document proprement.
            while not machine.is_complete():
                forced = machine.forced_continuation()
                machine.feed_text(forced)
                pieces.append(forced)
        return "".join(pieces)

    # Checkpointing

    def export_merged_state(self) -> dict[str, Any]:
        """Refond les LoRA dans les poids de base, et rend un checkpoint d'inference.

        Note: this mutates the model (adapters are merged away).
        """
        merge_lora(self.lm)
        self.lora_rank = 0
        return {
            "model_state": self.state_dict(),
            "config": {
                "clip_model": CLIP_MODEL,
                "lm_model": LM_MODEL,
                "lang_dim": LANG_DIM,
                "num_visual_tokens": NUM_VISUAL_TOKENS,
                "lora_merged": True,
            },
        }

    @classmethod
    def from_merged_checkpoint(
        cls, path: str | Path, device: str = "cpu"
    ) -> "ReceiptVLM":
        """Load a merged (adapter-free) checkpoint produced by export."""
        checkpoint = torch.load(str(path), map_location=device, weights_only=False)
        model = cls(lora_rank=0)
        model.load_state_dict(checkpoint["model_state"])
        model.to(device)
        model.eval()
        return model
