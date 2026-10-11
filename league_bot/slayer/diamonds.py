"""Fail-closed calibrated reading of the Slayer header's diamond balance."""
from __future__ import annotations

import re


from league_bot.macro import MacroError

from .diamond_glyphs import read_header_digits
_BALANCE = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)")
_FRAME_SIZE = (434, 810)
_HEADER_BOX = (252, 49, 300, 70)


def parse_diamond_text(text: str) -> int:
    """Parse a complete balance; reject labels, suffixes and bad grouping."""
    candidate = " ".join(text.split())
    if not _BALANCE.fullmatch(candidate):
        raise MacroError(f"saldo de diamantes ilegível: {text!r}")
    return int(candidate.replace(",", ""))


class _FrameImage:
    """Read-only RGB view over a captured Frame; no imaging dependency."""
    def __init__(self, frame, box=None):
        self.frame = frame
        self.box = box or (0, 0, frame.width, frame.height)
        self.width, self.height = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.size = (self.width, self.height)

    def convert(self, mode):
        if mode != "RGB":
            raise ValueError("Only RGB views are supported")
        return self

    def getpixel(self, xy):
        x, y = xy
        return self.frame.pixel(x + self.box[0], y + self.box[1])

    def __getitem__(self, xy):
        return self.getpixel(xy)

    def load(self):
        return self

    def crop(self, box):
        left, top = self.box[:2]
        return _FrameImage(self.frame, (box[0] + left, box[1] + top, box[2] + left, box[3] + top))


def _frame_image(frame):
    from league_bot.imaging import Frame
    width, height = getattr(frame, "width", None), getattr(frame, "height", None)
    pixels = getattr(frame, "bgr", None)
    if (width, height) != _FRAME_SIZE or pixels is None:
        raise MacroError("tamanho ou formato de frame inesperado para ler diamantes")
    try:
        return _FrameImage(Frame(width, height, pixels))
    except (ValueError, TypeError) as exc:
        raise MacroError("buffer de frame inválido para ler diamantes") from exc


def read_diamonds(frame) -> int:
    """Read the full balance next to the cyan diamond icon or raise MacroError."""
    image = _frame_image(frame)
    # Include the icon as a guard against unrelated nearby UI text.
    icon = image.crop((241, 51, 251, 70)).convert("RGB")
    icon_pixels = icon.load()
    cyan = sum(
        1 for y in range(icon.height) for x in range(icon.width)
        if (lambda rgb: rgb[2] > 130 and rgb[1] > 100 and rgb[2] > rgb[0] * 1.3)(icon_pixels[x, y])
    )
    if cyan < 8:
        raise MacroError("ícone de diamante não encontrado no cabeçalho")
    # The crop ends at x=300. Reject a count that visibly reaches that edge.
    edge = image.crop((298, 49, 300, 70)).convert("RGB").load()
    if any(min(edge[x, y]) > 150 and max(edge[x, y]) - min(edge[x, y]) < 80
           for x in range(2) for y in range(21)):
        raise MacroError("saldo de diamantes pode estar cortado")

    return read_header_digits(image.crop(_HEADER_BOX))
