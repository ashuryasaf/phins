"""Build downloadable HTML and PDF of the Executive Actuary Meeting Briefing.

Run: python3 business_plan/build_actuary_briefing.py
Outputs in business_plan/:
  - Executive_Actuary_Meeting_Briefing.html
  - Executive_Actuary_Meeting_Briefing.pdf
"""
from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Executive_Actuary_Meeting_Briefing.md"
HTML_OUT = ROOT / "Executive_Actuary_Meeting_Briefing.html"
PDF_OUT = ROOT / "Executive_Actuary_Meeting_Briefing.pdf"


def md_to_html(md: str) -> str:
    """Tiny purpose-built Markdown to HTML converter for this document.

    Handles: headings, paragraphs, bold/italic, inline code, hr, unordered
    lists, ordered lists, task-list checkboxes, GitHub-style tables, and
    blockquotes. Sufficient for the briefing; not a general parser.
    """
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    def inline(text: str) -> str:
        text = html_lib.escape(text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        return text

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("---") and set(stripped) == {"-"}:
            out.append("<hr/>")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|\s*[:\-\s|]+\|\s*$", lines[i + 1].strip()):
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            body_rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                body_rows.append(row)
                i += 1
            out.append("<table>")
            out.append("<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header_cells) + "</tr></thead>")
            out.append("<tbody>")
            for row in body_rows:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue

        if re.match(r"^(\-|\*)\s+", stripped):
            items: list[str] = []
            while i < n and re.match(r"^\s*(\-|\*)\s+", lines[i]):
                item_text = re.sub(r"^\s*(\-|\*)\s+", "", lines[i])
                cb = re.match(r"^\[( |x|X)\]\s+(.*)$", item_text)
                if cb:
                    checked = "checked" if cb.group(1).lower() == "x" else ""
                    items.append(
                        f'<li class="task"><input type="checkbox" disabled {checked}/> {inline(cb.group(2))}</li>'
                    )
                else:
                    items.append(f"<li>{inline(item_text)}</li>")
                i += 1
                while i < n and lines[i].startswith("    ") and not re.match(r"^\s*(\-|\*)\s+", lines[i]):
                    items[-1] = items[-1][:-5] + " " + inline(lines[i].strip()) + "</li>"
                    i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", stripped):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+\.\s+", "", lines[i])
                items.append(f"<li>{inline(item_text)}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        para = [stripped]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6}\s+|\||\-\s+|\*\s+|\d+\.\s+|>|---)", lines[i].strip()
        ):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(para)) + "</p>")

    return "\n".join(out)


CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 9pt;
    color: #888;
  }
  @bottom-left {
    content: "PHINS - Executive Actuary Meeting Briefing - Confidential";
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    font-size: 9pt;
    color: #888;
  }
}
html { font-size: 10.5pt; }
body {
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #1a1f2c;
  line-height: 1.5;
  max-width: 760px;
  margin: 0 auto;
  padding: 24px;
}
h1 {
  font-size: 22pt;
  color: #0b2545;
  border-bottom: 3px solid #0b2545;
  padding-bottom: 8px;
  margin-top: 0;
}
h2 {
  font-size: 15pt;
  color: #0b2545;
  margin-top: 28px;
  border-bottom: 1px solid #d4dae6;
  padding-bottom: 4px;
  page-break-after: avoid;
}
h3 {
  font-size: 12.5pt;
  color: #13315c;
  margin-top: 18px;
  page-break-after: avoid;
}
h4, h5, h6 { color: #13315c; margin-top: 14px; }
p { margin: 8px 0; text-align: justify; }
ul, ol { margin: 6px 0 10px 22px; padding: 0; }
li { margin: 3px 0; }
li.task { list-style: none; margin-left: -18px; }
li.task input { margin-right: 6px; }
code {
  background: #f1f3f8;
  border: 1px solid #e1e5ee;
  border-radius: 3px;
  padding: 1px 4px;
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: 9.5pt;
  color: #5a2ca0;
}
hr { border: none; border-top: 1px solid #d4dae6; margin: 18px 0; }
blockquote {
  border-left: 3px solid #0b2545;
  background: #f6f8fc;
  padding: 8px 14px;
  margin: 12px 0;
  color: #34405a;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #d4dae6;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #0b2545;
  color: #ffffff;
  font-weight: 600;
}
tr:nth-child(even) td { background: #f6f8fc; }
strong { color: #0b2545; }
.cover {
  border: 1px solid #d4dae6;
  background: #f6f8fc;
  padding: 14px 18px;
  border-radius: 6px;
  margin: 14px 0 22px 0;
  font-size: 10pt;
}
.cover strong { color: #0b2545; }
.confidential {
  text-align: center;
  font-size: 9pt;
  color: #8a3324;
  letter-spacing: 2px;
  text-transform: uppercase;
  margin-bottom: 4px;
}
"""


def build_html(md_text: str) -> str:
    body = md_to_html(md_text)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>PHINS - Executive Actuary Meeting Briefing</title>
<style>{CSS}</style>
</head>
<body>
<div class="confidential">Confidential - Internal Use Only</div>
{body}
</body>
</html>
"""


def main() -> None:
    md_text = SRC.read_text(encoding="utf-8")
    html_doc = build_html(md_text)
    HTML_OUT.write_text(html_doc, encoding="utf-8")
    print(f"wrote {HTML_OUT}")

    try:
        from weasyprint import HTML  # type: ignore

        HTML(string=html_doc, base_url=str(ROOT)).write_pdf(str(PDF_OUT))
        print(f"wrote {PDF_OUT}")
    except Exception as exc:  # pragma: no cover - best-effort PDF
        print(f"PDF generation skipped: {exc}")


if __name__ == "__main__":
    main()
