"""
codesheet.bylaw_extract — turn the bylaw PDF into structured clause records.

Output: data/bylaw/<edition>/articles.json — a list of
  {id, title, part, section, subsection, page, text, sentences:[{n, text}], tables:[...]}
one per Article (e.g. "3.2.2.49"). Sentences are split on the "1)" "2)" markers
the code uses. Tables are captured as raw text blocks keyed by "Table 3.2.2.49."
so the rule modules can parse the ones they need.

This is deliberately dumb and inspectable: regexes over extracted text, no ML.
When a rule module needs a clause, it reads it from here and carries the id
and page along, which is how every line on the code sheet gets its citation.
"""
from __future__ import annotations

import json, pathlib, re, sys
from pypdf import PdfReader

ART = re.compile(r'^(?P<id>\d\.\d{1,2}\.\d{1,2}\.\d{1,3})\.\s+(?P<title>[A-Z][^\n]{1,120})$', re.M)
SENT = re.compile(r'(?m)^\s*(\d{1,2})\)\s?')
TABLE = re.compile(r'^Table (\d\.\d{1,2}\.\d{1,2}\.\d{1,3})\.(?:-?[A-Z])?\s*$', re.M)

# Titles that are really page furniture, not articles.
JUNK_TITLES = re.compile(r'Division B|British Columbia Building Code|Vancouver Building By-law|^\d|^(or|and|to|of)\b|\bshall\b|\bis permitted\b|\.$', re.I)


def extract(pdf: pathlib.Path, part: int, first_page: int, last_page: int) -> list[dict]:
    r = PdfReader(pdf)
    pages = []
    for i in range(first_page - 1, min(last_page, len(r.pages))):
        t = r.pages[i].extract_text() or ''
        pages.append((i + 1, t))

    # concatenate with page markers so we can attribute an article to a page
    joined = ''
    offsets = []
    for pno, t in pages:
        offsets.append((len(joined), pno))
        joined += t + '\n'

    def page_of(pos):
        p = offsets[0][1]
        for off, pno in offsets:
            if off <= pos:
                p = pno
            else:
                break
        return p

    hits = [m for m in ART.finditer(joined) if m.group('id').startswith(f'{part}.') and not JUNK_TITLES.search(m.group('title'))]
    # keep only the first occurrence of each id, in document order
    seen = set(); arts = []
    for m in hits:
        if m.group('id') in seen:
            continue
        seen.add(m.group('id')); arts.append(m)

    out = []
    for k, m in enumerate(arts):
        start = m.end()
        end = arts[k + 1].start() if k + 1 < len(arts) else len(joined)
        body = joined[start:end].strip()
        aid = m.group('id')
        p, s, ss, a = aid.split('.')
        # split sentences
        parts = SENT.split(body)
        sentences = []
        if len(parts) > 1:
            for n, txt in zip(parts[1::2], parts[2::2]):
                sentences.append({'n': int(n), 'text': re.sub(r'\s+', ' ', txt).strip()})
        tables = [t.group(1) for t in TABLE.finditer(body)]
        out.append({
            'id': aid, 'title': m.group('title').strip(),
            'part': int(p), 'section': f'{p}.{s}', 'subsection': f'{p}.{s}.{ss}',
            'page': page_of(m.start()),
            'text': body, 'sentences': sentences, 'tables': tables,
        })
    return out


if __name__ == '__main__':
    root = pathlib.Path(__file__).resolve().parents[1]
    edition = sys.argv[1] if len(sys.argv) > 1 else 'vbbl-2025'
    cfg = {
        'vbbl-2025': dict(pdf=root / 'data/bylaw/vbbl-2025-vol1.pdf', part=3, first_page=100, last_page=420),
        'bcbc-2024': dict(pdf=root / 'data/bylaw/bcbc-2024-rev2.pdf', part=3, first_page=150, last_page=520),
    }[edition]
    arts = extract(**cfg)
    outdir = root / 'data/bylaw' / edition
    outdir.mkdir(exist_ok=True)
    (outdir / 'articles.json').write_text(json.dumps(arts, indent=1, ensure_ascii=False), encoding="utf-8")
    print(edition, len(arts), 'articles ->', outdir / 'articles.json')
    for a in arts:
        if a['id'] in ('3.1.2.1', '3.1.3.1', '3.1.10.1', '3.1.18.1', '3.2.2.10', '3.2.2.47', '3.2.2.48', '3.2.2.49', '3.2.2.51', '3.2.3.1', '3.2.3.7'):
            print(f"  {a['id']:10} p{a['page']:<4} {len(a['sentences'])} sentences  tables={a['tables']}  {a['title']}")
