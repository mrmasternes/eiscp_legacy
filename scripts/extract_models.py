"""Generate custom_components/eiscp_legacy/models.py from the Onkyo ISCP spec PDF.

Usage:
    python scripts/extract_models.py ONKYO_CMDS.pdf [output.py]

Requires ``pdfplumber``. The spec ("ISCP Spec - Receivers" v1.15) contains three
groups of model columns:

* group 1 - pages 6-15: row labels and Yes/No cells share the page.
* group 2 - pages 16-25: only Yes/No cells and the model header; the row labels
  are those of the same table on pages 6-15 (identical row y-positions).
* group 3 - pages 26-35: same as group 2.

Each Yes/No cell is assigned to a model column by its x position; the model
header of a column is read from the characters above the table, grouped by the
same x bands. As an independent check, the sequence of values of every row
(by position) must also occur as a line in the page's plain text order.
"""

from __future__ import annotations

import itertools
import re
import sys

import pdfplumber

VALUE = re.compile(r"(Yes|No)(\(\*\d\)|\*\d)?")
CODE_LABEL = re.compile(r"^[\"“”]([0-9A-F]{2})[\"“”]\s+(sets|gets)\b")
# (labels page, data page) per section, per group
GROUPS = {
    1: {"SLI": (8, 8), "LMD": (9, 9)},
    2: {"SLI": (8, 18), "LMD": (9, 19)},
    3: {"SLI": (8, 28), "LMD": (9, 29)},
}
SECTION_START = {"SLI": '"SLI"', "LMD": '"LMD"'}
SECTION_END = {"SLI": '"SLR"', "LMD": '"LTN"'}

# Header cells that the PDF wraps in a way that cannot be split mechanically.
HEADER_OVERRIDES = {
    ("DTX-7DTR-", "8.4DTR-", "7.4"): ["DTX-7", "DTR-8.4", "DTR-7.4"],
    ("TX-NR1000", "TX-", "NR5000ET", "X-NA1000", "DTR-10.5", "RDC-7.1"): [
        "TX-NR1000",
        "TX-NR5000E",
        "TX-NA1000",
        "DTR-10.5",
        "RDC-7.1",
    ],
    ("PR-", "SC5507"): ["PR-SC5507"],
}
# Models listed in two different columns of the same table (ambiguous).
AMBIGUOUS = {"TX-DS989", "RDC-7"}
INTEGRA_PREFIXES = ("DTC", "DHC", "DTR", "DTX", "RDC")


def column_of(x, centres):
    bounds = [(a + b) / 2 for a, b in itertools.pairwise(centres)]
    return sum(1 for b in bounds if x > b)


def data_columns(page):
    """Return (x centres of the Yes/No columns, value words, top of first row)."""
    words = [w for w in page.extract_words() if VALUE.fullmatch(w["text"])]
    clusters: list[list[float]] = []
    for x in sorted((w["x0"] + w["x1"]) / 2 for w in words):
        if clusters and x - clusters[-1][-1] < 6:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    biggest = max(len(c) for c in clusters)
    centres = [sum(c) / len(c) for c in clusters if len(c) > biggest / 2]
    return centres, words, min(w["top"] for w in words)


def header_models(page, centres, first_top):
    cells: list[dict[int, list]] = [{} for _ in centres]
    half = (centres[1] - centres[0]) / 2
    for ch in page.chars:
        x = (ch["x0"] + ch["x1"]) / 2
        if (
            centres[0] - half < x < centres[-1] + half
            and 100 < ch["top"] < first_top - 3
            and ch["text"].strip()
        ):
            col = column_of(x, centres)
            cells[col].setdefault(round(ch["top"]), []).append(ch)
    result = []
    for cell in cells:
        lines = tuple(
            "".join(c["text"] for c in sorted(cell[k], key=lambda c: c["x0"])) for k in sorted(cell)
        )
        lines = tuple(ln for ln in lines if ln != "(Ver2.0)")
        if lines in HEADER_OVERRIDES:
            result.append(HEADER_OVERRIDES[lines])
            continue
        for ln in lines:
            if not re.fullmatch(r"[A-Z]{2,3}-[A-Z]*\d+(\.\d+)?[A-Z]*", ln):
                raise SystemExit(f"cannot parse header cell {lines!r}")
        result.append(list(lines))
    return result


def label_rows(page, section):
    """[(top, code, text)] of the code rows of a section on the label page."""
    lines = page.extract_text_lines()
    start = next(i for i, ln in enumerate(lines) if ln["text"].startswith(SECTION_START[section]))
    rows = []
    for ln in lines[start + 1 :]:
        if ln["text"].startswith(SECTION_END[section]):
            break
        m = CODE_LABEL.match(ln["text"])
        if m:
            rows.append((ln["top"], m.group(1), ln["text"]))
    return rows


def extract(pdf_path):
    pdf = pdfplumber.open(pdf_path)
    profiles: dict[str, dict[str, list[str]]] = {}
    checks = 0
    for sections in GROUPS.values():
        for section, (label_pn, data_pn) in sections.items():
            labels = label_rows(pdf.pages[label_pn - 1], section)
            page = pdf.pages[data_pn - 1]
            centres, words, first_top = data_columns(page)
            models = header_models(page, centres, first_top)
            n = len(centres)
            text_rows = set()
            for line in (page.extract_text() or "").split("\n"):
                vals = [t.startswith("Yes") for t in line.split() if VALUE.fullmatch(t)]
                if len(vals) >= n:
                    text_rows.add(tuple(vals[-n:]))
            for top, code, _text in labels:
                cells = {}
                for w in words:
                    if abs(w["top"] - top) < 2.5:
                        cells[column_of((w["x0"] + w["x1"]) / 2, centres)] = w["text"].startswith(
                            "Yes"
                        )
                if len(cells) != n:
                    raise SystemExit(f"{section} {code}: {len(cells)} cells at y={top}")
                if tuple(cells[i] for i in range(n)) not in text_rows:
                    raise SystemExit(f"text-order mismatch: {section} {code} page {data_pn}")
                checks += 1
                for col, ok in cells.items():
                    for model in models[col]:
                        if model in AMBIGUOUS:
                            continue
                        entry = profiles.setdefault(model, {"SLI": [], "LMD": []})
                        if ok and code not in entry[section]:
                            entry[section].append(code)
    print(f"{checks} rows cross-checked against text order", file=sys.stderr)
    return profiles


def slug(model):
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def display(model):
    brand = "Integra" if model.startswith(INTEGRA_PREFIXES) else "Onkyo"
    return f"{brand} {model}"


HEADER = '''"""Per-model input and listening mode support.

Generated by ``scripts/extract_models.py`` from the Onkyo "ISCP Spec - Receivers"
v1.15 (Aug 2009) command support tables ("SLI" input selector and "LMD"
listening mode). Do not edit the data by hand; re-run the generator instead.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Inputs and listening modes a receiver model supports."""

    key: str
    name: str
    sources: tuple[str, ...]
    listening_modes: tuple[str, ...]


MODEL_OTHER = "other"

# fmt: off
MODELS: dict[str, ModelProfile] = {
'''

FOOTER = '''}
# fmt: on


def get_profile(key: str | None) -> ModelProfile | None:
    """Return the profile for a model key, or None for "other"/unknown."""
    if key is None:
        return None
    return MODELS.get(key)


def model_choices() -> list[tuple[str, str]]:
    """Return (key, name) pairs sorted by name, excluding "other"."""
    return sorted(((p.key, p.name) for p in MODELS.values()), key=lambda c: c[1])
'''


def fmt_tuple(codes, per_line=10):
    if not codes:
        return "()"
    rows = [
        "            " + ", ".join(f'"{c}"' for c in codes[i : i + per_line]) + ","
        for i in range(0, len(codes), per_line)
    ]
    return "(\n" + "\n".join(rows) + "\n        )"


def render(profiles):
    out = [HEADER]
    for model in sorted(profiles, key=display):
        p = profiles[model]
        out.append(
            f'    "{slug(model)}": ModelProfile(\n'
            f'        key="{slug(model)}",\n'
            f'        name="{display(model)}",\n'
            f"        sources={fmt_tuple(p['SLI'])},\n"
            f"        listening_modes={fmt_tuple(p['LMD'])},\n"
            f"    ),\n"
        )
    out.append(FOOTER)
    return "".join(out)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    text = render(extract(sys.argv[1]))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
