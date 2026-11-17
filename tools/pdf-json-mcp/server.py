"""PDF -> compact JSON MCP server (local, no external services).

Extracts text and tables per page with pdfplumber so Claude can read
structured text instead of the raw PDF (fewer tokens). Scanned PDFs
without a text layer need OCR first (reported via `scanned_pages`).
"""
import json
from pathlib import Path

import pdfplumber
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("pdf-json")


def _parse_pages(spec: str | None, total: int) -> list[int]:
    """'1-3,7' -> [1,2,3,7] (1-based). None -> all pages."""
    if not spec:
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        elif part:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= total)


@mcp.tool()
def pdf_info(path: str) -> str:
    """Return page count and metadata of a PDF (cheap; call before pdf_to_json)."""
    with pdfplumber.open(path) as pdf:
        return json.dumps(
            {"file": Path(path).name, "pages": len(pdf.pages), "metadata": pdf.metadata},
            ensure_ascii=False,
            default=str,
        )


@mcp.tool()
def pdf_to_json(
    path: str,
    pages: str | None = None,
    include_tables: bool = True,
    save_to: str | None = None,
    max_chars: int = 30000,
) -> str:
    """Convert a PDF to compact JSON: {file, pages:[{page, text, tables}], scanned_pages}.

    pages: e.g. "1-3,7" (1-based, default all). save_to: also write the full
    JSON to this path. If output exceeds max_chars it is truncated in the
    reply (use save_to or the pages argument to read the rest).
    """
    out_pages, scanned = [], []
    with pdfplumber.open(path) as pdf:
        for n in _parse_pages(pages, len(pdf.pages)):
            page = pdf.pages[n - 1]
            text = (page.extract_text() or "").strip()
            entry: dict = {"page": n, "text": text}
            if not text:
                scanned.append(n)
            if include_tables:
                tables = [
                    [[(c or "").strip() for c in row] for row in t]
                    for t in page.extract_tables()
                ]
                if tables:
                    entry["tables"] = tables
            out_pages.append(entry)
    result = {"file": Path(path).name, "pages": out_pages, "scanned_pages": scanned}
    full = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if save_to:
        Path(save_to).write_text(full, encoding="utf-8")
    if len(full) > max_chars:
        return full[:max_chars] + f'..."TRUNCATED":{len(full)} chars total, use pages or save_to'
    return full


if __name__ == "__main__":
    mcp.run()
