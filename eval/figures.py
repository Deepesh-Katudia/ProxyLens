"""Confusion-matrix figure as a standalone SVG (renders on GitHub, no plotting library)."""

from html import escape

from eval.metrics import INVALID, TYPE_ORDER

CELL = 30
LABEL_W = 250
HEADER_H = 190


def _short(label: str) -> str:
    return label.replace("_", " ").lower()


def confusion_svg(confusion: dict[str, dict[str, int]], title: str) -> str:
    rows = [t for t in TYPE_ORDER if t in confusion]
    predicted = {p for row in confusion.values() for p in row}
    cols = [t for t in [*TYPE_ORDER, INVALID] if t in predicted or t in rows]
    peak = max((v for row in confusion.values() for v in row.values()), default=1)
    width = LABEL_W + CELL * len(cols) + 20
    height = HEADER_H + CELL * len(rows) + 40
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="system-ui, sans-serif" font-size="11">',
        '<rect width="100%" height="100%" fill="#fbfaf7"/>',
        f'<text x="10" y="20" font-size="14" font-weight="600">{escape(title)}</text>',
        f'<text x="10" y="{HEADER_H - 8}" fill="#666">reference ↓ / predicted →</text>',
    ]
    for j, col in enumerate(cols):
        x = LABEL_W + j * CELL + CELL / 2
        parts.append(
            f'<text transform="translate({x + 4},{HEADER_H - 6}) rotate(-60)" '
            f'fill="{"#a33" if col == INVALID else "#333"}">{escape(_short(col))}</text>'
        )
    for i, row in enumerate(rows):
        y = HEADER_H + i * CELL
        parts.append(
            f'<text x="{LABEL_W - 8}" y="{y + CELL / 2 + 4}" text-anchor="end">'
            f"{escape(_short(row))}</text>"
        )
        for j, col in enumerate(cols):
            value = confusion.get(row, {}).get(col, 0)
            x = LABEL_W + j * CELL
            shade = value / peak if peak else 0
            if value and row == col:
                fill = f"rgba(30,130,80,{0.15 + 0.85 * shade:.2f})"
            elif value:
                fill = f"rgba(180,50,40,{0.15 + 0.85 * shade:.2f})"
            else:
                fill = "#ffffff"
            parts.append(
                f'<rect x="{x}" y="{y}" width="{CELL - 2}" height="{CELL - 2}" fill="{fill}" '
                'stroke="#e5e2da"/>'
            )
            if value:
                color = "#fff" if shade > 0.55 else "#222"
                parts.append(
                    f'<text x="{x + CELL / 2 - 1}" y="{y + CELL / 2 + 4}" text-anchor="middle" '
                    f'fill="{color}">{value}</text>'
                )
    parts.append("</svg>")
    return "\n".join(parts)
