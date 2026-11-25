"""PDF scout-report extraction (Django port of the FastAPI track's parser).

Same behaviour: section-aware regexes over bio/career tables, glossary and
match pages excluded so totals can't double-count and glossary words
(e.g. "goalkeeper") can't win the position vote. Raises ValueError when
the file can't be read.
"""

import io
import re

NUMERIC_FIELDS = [
    "height_in_cm",
    "international_caps",
    "market_value_in_eur",
    "matches_played",
    "total_minutes",
    "total_goals",
    "total_assists",
    "yellow_cards",
    "red_cards",
]

CATEGORICAL_FIELDS = [
    "position",
    "sub_position",
    "foot",
    "competition_code",
    "confederation",
]

ALL_FIELDS = NUMERIC_FIELDS + CATEGORICAL_FIELDS

SUB_POSITIONS = [
    "Centre-Forward", "Left Winger", "Right Winger", "Second Striker",
    "Attacking Midfield", "Central Midfield", "Defensive Midfield",
    "Left Midfield", "Right Midfield",
    "Centre-Back", "Left-Back", "Right-Back",
    "Goalkeeper",
]

COMPETITION_ALIASES = {
    "premier league": "premier-league",
    "laliga": "laliga",
    "la liga": "laliga",
    "serie a": "serie-a",
    "bundesliga": "bundesliga",
    "ligue 1": "ligue-1",
    "eredivisie": "eredivisie",
    "liga portugal": "liga-portugal",
    "major league soccer": "major-league-soccer",
    "mls": "major-league-soccer",
    "saudi pro league": "saudi-pro-league",
    "superliga": "superliga",
}


def extract_pdf_text(raw: bytes) -> str:
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join([(p.extract_text() or "") for p in reader.pages]).strip()
        if text:
            return text
    except ImportError:
        raise ValueError("PDF libraries missing. Run: pip install pdfplumber pypdf")
    raise ValueError("Could not extract text from this PDF.")


def _number_after_label(head: str, label_pat: str, lo: float, hi: float, window: int = 80):
    m = re.search(label_pat, head, re.IGNORECASE)
    if not m:
        return None
    for num in re.finditer(r"(\d{2,4}(?:[,\.]\d+)?)", head[m.end():m.end() + window]):
        try:
            v = float(num.group(1).replace(",", ""))
        except ValueError:
            continue
        if lo <= v <= hi:
            return v
    return None


def parse_report_text(text: str) -> dict:
    t = text or ""
    out: dict = {k: None for k in ALL_FIELDS}

    pre_rank = re.split(r"PLAYER REPORT\s*RANKINGS", t, flags=re.IGNORECASE)[0]
    head = re.split(r"\bGLOSSARY\b", pre_rank, flags=re.IGNORECASE)[0]
    head_low = head.lower()
    pos_scope_low = re.split(r"\bGLOSSARY\b", t, flags=re.IGNORECASE)[0].lower()
    if re.search(r"\bPROFILE\b", head, re.IGNORECASE):
        career_seg = re.split(r"\bPROFILE\b", head, flags=re.IGNORECASE)[-1]
    else:
        career_seg = head

    out["height_in_cm"] = _number_after_label(head, r"height", 140, 210)

    m = re.search(r"(strong foot|preferred foot|dominant foot|\bfoot\b)", head, re.IGNORECASE)
    if m:
        w = re.search(r"\b(left|right|both)\b", head[m.end():m.end() + 80], re.IGNORECASE)
        if w:
            out["foot"] = w.group(1).lower()

    group_m = re.search(r"rankings for ([\w\s/\-]+?) in ", pos_scope_low)
    group = group_m.group(1).strip() if group_m else ""
    if re.search(r"defender|centre-back|center-back|full.back|wing.back|\bback\b", group):
        out["position"] = "Defender"
    elif re.search(r"midfield", group):
        out["position"] = "Midfield"
    elif re.search(r"forward|striker|winger|\battack\b", group):
        out["position"] = "Attack"
    elif re.search(r"goalkeeper|goal keeper", group):
        out["position"] = "Goalkeeper"
    elif re.search(
        r"central defender|centre-back|center-back|left-back|right-back|full-back|wing-back|centre back|\bdefender\b",
        head_low,
    ):
        out["position"] = "Defender"
    elif re.search(r"midfield", head_low):
        out["position"] = "Midfield"
    elif re.search(r"centre-forward|second striker|striker|winger|\bforward\b|\battack\b", head_low):
        out["position"] = "Attack"
    elif re.search(r"goalkeeper|goal keeper", head_low):
        out["position"] = "Goalkeeper"

    for sp in SUB_POSITIONS:
        if re.search(r"\b" + re.escape(sp) + r"\b", head, re.IGNORECASE):
            out["sub_position"] = sp
            break
    if out["sub_position"] is None:
        if re.search(r"central defender|centre.back", group):
            out["sub_position"] = "Centre-Back"
        elif re.search(r"left", group) and re.search(r"back|wingback|wing.back", group):
            out["sub_position"] = "Left-Back"
        elif re.search(r"right", group) and re.search(r"back|wingback|wing.back", group):
            out["sub_position"] = "Right-Back"
        elif re.search(r"central defender|centre back|centre-back", head_low):
            out["sub_position"] = "Centre-Back"
        elif re.search(r"left.back|left wing-back", head_low):
            out["sub_position"] = "Left-Back"
        elif re.search(r"right.back|right wing-back", head_low):
            out["sub_position"] = "Right-Back"

    for alias, code in COMPETITION_ALIASES.items():
        if alias in head_low:
            out["competition_code"] = code
            break

    if re.search(r"europa|europe|uefa|england|premier league|chelsea|bundesliga|serie a|laliga|ligue 1", head_low):
        out["confederation"] = "europa"
    elif re.search(r"amerika|americas|mls|brasil|brazil|argentina|liga mx|concacaf|conmebol", head_low):
        out["confederation"] = "amerika"
    elif re.search(r"asien|asia|afc|j1 league|k league", head_low):
        out["confederation"] = "asien"

    row_pat = re.compile(r"(\d{2,5})\s+(\d{1,3})\s*/\s*(\d{1,3})\s+(\d{1,3})\s*/\s*(\d{1,3})")
    minutes_total, apps_total, y_total, r_total = 0, 0, 0, 0
    nat_caps = 0
    hits = 0
    seen_rows = set()
    for line in career_seg.splitlines():
        mrow = row_pat.search(line)
        if mrow:
            try:
                mins, apps, _starts, yel, red = map(int, mrow.groups())
            except ValueError:
                continue
            if not (1 <= apps <= 1000 and mins <= 60000):
                continue
            if mins < apps or mins / apps > 130:
                continue
            if yel > apps or red > apps or red > 30:
                continue
            norm = re.sub(r"\s+", " ", line.strip())
            if norm in seen_rows:
                continue
            seen_rows.add(norm)
            minutes_total += mins
            apps_total += apps
            y_total += yel
            r_total += red
            hits += 1
    seen_nat = set()
    for line in pre_rank.splitlines():
        for mrow in row_pat.finditer(line):
            if not re.search(r"england|national team|u21|u19|u18|u17", line[:mrow.start()], re.IGNORECASE):
                continue
            try:
                mins, apps, _starts, _yel, _red = map(int, mrow.groups())
            except ValueError:
                continue
            if mins < apps or (mins, apps) in seen_nat:
                continue
            seen_nat.add((mins, apps))
            nat_caps += apps
    if hits > 0:
        out["total_minutes"] = float(minutes_total)
        out["matches_played"] = float(apps_total)
        out["yellow_cards"] = float(y_total)
        out["red_cards"] = float(r_total)
        if nat_caps > 0:
            out["international_caps"] = float(nat_caps)

    m = re.search(
        r"market value[^\d€£$]{0,20}[€£$]?\s*([\d,\.]+)\s*(m|million|k|thousand)?",
        t, re.IGNORECASE,
    )
    if not m:
        m = re.search(r"est\.?\s*value\s*[€£$]?\s*([\d,\.]+)\s*(m|million|k|thousand)?", t, re.IGNORECASE)
    if not m:
        m = re.search(r"[€]\s*([\d,\.]+)\s*(m|million|k|thousand)?", t)
    if m:
        try:
            num = float(m.group(1).replace(",", ""))
            mult = (m.group(2) or "").lower()
            if mult in ("m", "million"):
                num *= 1_000_000
            elif mult in ("k", "thousand"):
                num *= 1_000
            if 0 < num < 500_000_000:
                out["market_value_in_eur"] = num
        except ValueError:
            pass

    m = re.search(r"total goals\s*[:\-]?\s*(\d+)", t, re.IGNORECASE)
    if m:
        out["total_goals"] = float(m.group(1))
    m = re.search(r"total assists\s*[:\-]?\s*(\d+)", t, re.IGNORECASE)
    if m:
        out["total_assists"] = float(m.group(1))

    return out
