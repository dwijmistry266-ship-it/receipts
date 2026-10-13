#!/usr/bin/env python3
"""Classified-dossier SVG banner generator.

Generates the 1200x360 "CASE FILE" banner used across the dossier-themed
repos. Visual language: dossier black bg, amber evidence tape, red rubber
stamps, redaction bars, typewriter mono.

Usage:
    python scripts/gen_banner.py --title RECEIPTS --case-no 002 \
        --tagline "SLOP-DETECTION DIVISION // AI-DEV-TOOLS UNIT" \
        --filed 2026-10-14 --output assets/banner.svg
"""

import argparse
import random

W, H = 1200, 360
BG = "#0B0B0C"
INK = "#F5F2EA"
RED = "#E63946"
AMBER = "#FFB000"
MANILA = "#E8E3D3"
MONO = "'Courier New', Courier, monospace"


def _grid() -> str:
    lines = []
    for x in range(0, W + 1, 40):
        lines.append(
            '<line x1="%d" y1="0" x2="%d" y2="%d" stroke="%s" '
            'stroke-width="1" opacity="0.05"/>' % (x, x, H, INK)
        )
    for y in range(0, H + 1, 40):
        lines.append(
            '<line x1="0" y1="%d" x2="%d" y2="%d" stroke="%s" '
            'stroke-width="1" opacity="0.05"/>' % (y, W, y, INK)
        )
    return "\n".join(lines)


def _evidence_tape(y: int, h: int) -> str:
    parts = [
        '<rect x="0" y="%d" width="%d" height="%d" fill="%s"/>' % (y, W, h, AMBER),
        '<rect x="0" y="%d" width="%d" height="2" fill="#000" opacity="0.35"/>' % (y + h - 2, W),
    ]
    x = 12
    while x < W:
        parts.append(
            '<text x="%d" y="%d" font-family="%s" font-size="22" '
            'font-weight="bold" fill="#0B0B0C" letter-spacing="4">EVIDENCE</text>'
            % (x, y + h - 14, MONO)
        )
        x += 190
    return "\n".join(parts)


def _stamp(cx: int, cy: int, text: str, size: int = 34) -> str:
    w = len(text) * size * 0.72 + 44
    h = size + 36
    return (
        '<g transform="rotate(-8 %d %d)" opacity="0.92">'
        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" '
        'stroke="%s" stroke-width="5"/>'
        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="none" '
        'stroke="%s" stroke-width="2" stroke-dasharray="10 6"/>'
        '<text x="%d" y="%d" font-family="%s" font-size="%d" font-weight="bold" '
        'fill="%s" text-anchor="middle" letter-spacing="6">%s</text>'
        "</g>"
        % (cx, cy,
           cx - w / 2, cy - h / 2, w, h, RED,
           cx - w / 2 + 9, cy - h / 2 + 9, w - 18, h - 18, RED,
           cx, cy + size * 0.36, MONO, size, RED, text)
    )


def _barcode(x: int, y: int, seed: int = 7) -> str:
    rng = random.Random(seed)
    parts = []
    cx = x
    while cx < x + 180:
        bw = rng.choice([2, 3, 4, 6])
        if rng.random() > 0.35:
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="44" fill="%s"/>'
                % (cx, y, bw, INK)
            )
        cx += bw + rng.choice([2, 3, 4])
    parts.append(
        '<text x="%d" y="%d" font-family="%s" font-size="11" fill="%s" '
        'letter-spacing="3">FILE-%04d</text>' % (x, y + 60, MONO, MANILA, seed)
    )
    return "\n".join(parts)


def generate(title: str, case_no: str, tagline: str, filed: str,
            redacted: str) -> str:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">' % (W, H, W, H),
        '<rect width="%d" height="%d" fill="%s"/>' % (W, H, BG),
        _grid(),
        _evidence_tape(0, 44),
        # Case file header.
        '<text x="40" y="92" font-family="%s" font-size="20" fill="%s" '
        'letter-spacing="8">CASE FILE #%s</text>' % (MONO, MANILA, case_no),
        # Giant typewriter wordmark.
        '<text x="38" y="208" font-family="%s" font-size="118" '
        'font-weight="bold" fill="%s" letter-spacing="10">%s</text>'
        % (MONO, INK, title.upper()),
        # Redacted privacy-joke line.
        '<text x="40" y="252" font-family="%s" font-size="22" fill="%s" '
        'letter-spacing="2">SUBJECT:</text>' % (MONO, MANILA),
        '<rect x="170" y="228" width="%d" height="30" fill="#000" '
        'stroke="%s" stroke-width="1"/>' % (len(redacted) * 15, INK),
        '<text x="178" y="252" font-family="%s" font-size="22" fill="%s" '
        'letter-spacing="2">%s</text>' % (MONO, RED, redacted),
        # Division sub-line.
        '<text x="40" y="300" font-family="%s" font-size="19" fill="%s" '
        'letter-spacing="3">%s</text>' % (MONO, AMBER, tagline),
        # Filed date.
        '<text x="40" y="330" font-family="%s" font-size="17" fill="%s" '
        'letter-spacing="2">FILED: %s</text>' % (MONO, MANILA, filed),
        # Red stamp, right side.
        _stamp(985, 190, "CONFIDENTIAL"),
        # Barcode, bottom right.
        _barcode(990, 262, seed=int(case_no)),
        # Perforated cut line along the bottom.
        '<line x1="0" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2" '
        'stroke-dasharray="12 8" opacity="0.5"/>' % (H - 14, W, H - 14, MANILA),
        "</svg>",
    ]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a dossier-style banner.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--case-no", required=True)
    ap.add_argument("--tagline", required=True)
    ap.add_argument("--filed", required=True)
    ap.add_argument("--redacted", default="\u2588" * 12,
                    help="redaction-bar text after SUBJECT:")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    svg = generate(args.title, args.case_no, args.tagline, args.filed,
                   args.redacted)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("wrote", args.output)
    return 0


if __name__ == "__main__":
    main()
