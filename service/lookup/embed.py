"""Pinned SciBERT encoder shared by catalog construction and CPU queries."""

from collections.abc import Sequence

import torch
from transformers import AutoModel, AutoTokenizer


class LookupEmbedder:
    """Mean-pool and normalize SciBERT output with the original MVP contract."""

    def __init__(
        self,
        model_name: str,
        revision: str,
        max_tokens: int,
        device: str | None = None,
        require_cuda: bool = False,
    ) -> None:
        """Load the pinned model on the selected inference device."""
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self.model = AutoModel.from_pretrained(model_name, revision=revision)
        selected = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if require_cuda and (selected != "cuda" or not torch.cuda.is_available()):
            raise RuntimeError("CUDA was required but is not available in this environment")
        self.device = torch.device(selected)
        self.model.to(self.device)
        self.model.eval()
        self.max_tokens = max_tokens

    @torch.inference_mode()
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return normalized mean pooled vectors in input order."""
        batch = self.tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_tokens,
            return_tensors="pt",
        )
        batch = {key: value.to(self.device) for key, value in batch.items()}
        hidden = self.model(**batch).last_hidden_state
        mask = batch["attention_mask"].unsqueeze(-1).expand(hidden.size()).float()
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normalized.cpu().tolist()

    def encode_query(self, query: str) -> list[float]:
        """Encode one search query using the same pooling contract."""
        return self.encode([query])[0]
