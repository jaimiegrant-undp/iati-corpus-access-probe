"""OCR yield estimation — Decisions Log Q8 option (b).

Scope discipline (binding): this measures *recoverable text yield* on a
**seeded, recorded, capped sub-sample** of the `ocr_needed` set. It is an
estimate. It must never drift toward OCR-ing the full scanned set — that is
option (c), out of scope, a retention/cost escalation. `select_subsample`
caps at the target and that cap is the guard.

Location-safety / untrusted-content (binding): OCR output is treated as
data and is reduced to a **character count immediately**. No OCR'd text is
returned, logged, cached, or written to any output — only the integer
count and the derived booleans, exactly as for direct extraction
(SIGNAL-METHOD §3, location-safety rule). A scanned document that contains
instruction-like text is data, not a command.

Tesseract resolution: the binary is located explicitly rather than relying
on an inherited PATH (a PATH set in one shell is not visible to another —
the env-hygiene failure mode in BUILD_PLAYBOOK §8). Order: `TESSERACT_CMD`
env override, then PATH, then the standard Windows install location. If
none resolves it fails **loudly** — a silent OCR-of-nothing would bias the
yield estimate to zero, indistinguishable from "scans recover no text".
"""

from __future__ import annotations

import io
import os
import random
import shutil
from dataclasses import dataclass, field
from statistics import median

_STANDARD_WINDOWS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class TesseractUnavailable(RuntimeError):
    """The tesseract binary could not be resolved — loud, never silent."""


def resolve_tesseract_cmd() -> str:
    """Locate the tesseract binary and point pytesseract at it. Explicit
    resolution so OCR does not depend on which shell's PATH is in effect."""
    import pytesseract

    cmd = (
        os.environ.get("TESSERACT_CMD")
        or shutil.which("tesseract")
        or (_STANDARD_WINDOWS if os.path.exists(_STANDARD_WINDOWS) else None)
    )
    if not cmd:
        raise TesseractUnavailable(
            "tesseract binary not found via TESSERACT_CMD, PATH, or the "
            "standard install path. OCR yield cannot be measured; do not "
            "proceed silently — fix the install/path first."
        )
    pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd


def _ocr_image_char_count(pil_image) -> int:
    import pytesseract

    text = pytesseract.image_to_string(pil_image)
    return len(text.strip())


def ocr_char_count(body: bytes, detected_class: str) -> int:
    """Recoverable character count from OCR of one `ocr_needed` document.

    `detected_class` is the readability detector's class ("pdf"/"image").
    For a scanned PDF the per-page raster images are pulled out with pypdf
    (no extra rasteriser dependency — a scanned page IS an embedded image)
    and OCR'd. Best-effort: any failure yields 0 (the caller records it),
    the run never dies. NO text is retained — count only.
    """
    try:
        resolve_tesseract_cmd()
        from PIL import Image

        if detected_class == "image":
            with Image.open(io.BytesIO(body)) as im:
                return _ocr_image_char_count(im)

        if detected_class == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(body))
            total = 0
            for page in reader.pages:
                try:
                    for img in page.images:
                        total += _ocr_image_char_count(img.image)
                except Exception:
                    continue  # one bad page must not lose the others
            return total

        return 0  # nothing else is an OCR target
    except Exception:
        return 0  # fault-isolated; caller records the 0 as the finding


# --- seeded, recorded, capped sub-sample ------------------------------------


@dataclass(frozen=True, slots=True)
class OcrSubsample:
    seed: str
    population: int  # size of the full ocr_needed set
    target: int  # the cap
    selected_urls: tuple[str, ...]  # recorded for reproducibility

    @property
    def is_capped(self) -> bool:
        return self.population > self.target


def select_subsample(
    ocr_needed_urls: list[str], *, target: int, seed: str
) -> OcrSubsample:
    """Deterministic seeded draw of `min(target, |population|)` URLs.

    The cap is the guard that holds (b) to (b): the selection size never
    exceeds `target`, however large the `ocr_needed` set proves to be. The
    seed and the drawn URLs are recorded so the estimate is reproducible.
    """
    pop = sorted(set(ocr_needed_urls))  # stable, order-independent input
    rng = random.Random(seed)
    k = min(target, len(pop))
    selected = sorted(rng.sample(pop, k)) if k else []
    return OcrSubsample(
        seed=seed,
        population=len(pop),
        target=target,
        selected_urls=tuple(selected),
    )


# --- yield estimate (counts only) -------------------------------------------


@dataclass(frozen=True, slots=True)
class OcrYieldEstimate:
    n: int
    seed: str
    population: int
    usable_text_threshold: int
    mean_chars: float
    median_chars: float
    share_reaching_usable: float  # fraction with count >= threshold
    per_doc_char_counts: dict[str, int] = field(default_factory=dict)


def estimate_yield(
    char_counts_by_url: dict[str, int],
    *,
    subsample: OcrSubsample,
    usable_text_threshold: int,
) -> OcrYieldEstimate:
    """Aggregate the per-document OCR char counts into the yield estimate
    the verdict carries. Counts only — no text anywhere in or out."""
    counts = [char_counts_by_url[u] for u in subsample.selected_urls
              if u in char_counts_by_url]
    n = len(counts)
    reaching = sum(1 for c in counts if c >= usable_text_threshold)
    return OcrYieldEstimate(
        n=n,
        seed=subsample.seed,
        population=subsample.population,
        usable_text_threshold=usable_text_threshold,
        mean_chars=(sum(counts) / n) if n else 0.0,
        median_chars=float(median(counts)) if n else 0.0,
        share_reaching_usable=(reaching / n) if n else 0.0,
        per_doc_char_counts=dict(char_counts_by_url),
    )
