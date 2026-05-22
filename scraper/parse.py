import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.config import BASE_URL

ARTICLE_ID_RE = re.compile(r"pressemitteilung\.(\d+)\.php")
DATE_LIST_RE = re.compile(
    r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})\s+Uhr"
)
DATE_MELDUNG_RE = re.compile(r"Polizeimeldung vom\s+(\d{2})\.(\d{2})\.(\d{4})")
CASE_NUMBER_RE = re.compile(r"Nr\.\s*(\d+)")
INTERNAL_ID_RE = re.compile(r"^ii\d+$", re.I)
SKIP_TAG_RE = re.compile(
    r"^(Polizeimeldung|Meldung Polizei Berlin|Meldung der Polizei Berlin|Polizeimeldung vom)",
    re.I,
)


def article_id_from_url(url: str) -> str | None:
    match = ARTICLE_ID_RE.search(url)
    return match.group(1) if match else None


def absolute_url(href: str) -> str:
    return urljoin(BASE_URL, href)


def parse_tags_from_keywords(keywords: str) -> list[str]:
    if not keywords:
        return []
    tags: list[str] = []
    for part in keywords.split(","):
        part = part.strip()
        if not part or INTERNAL_ID_RE.match(part) or SKIP_TAG_RE.match(part):
            continue
        if part not in tags:
            tags.append(part)
    return tags


def parse_listing_page(html: str) -> tuple[list[dict], str | None]:
    """Parse overview page; return teaser rows and next page URL (if any)."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []

    for li in soup.select("ul li"):
        date_el = li.select_one(".cell.nowrap.date")
        link_el = li.select_one(".cell.text a[href*='pressemitteilung']")
        if not date_el or not link_el:
            continue

        href = link_el.get("href", "")
        article_id = article_id_from_url(href)
        if not article_id:
            continue

        date_match = DATE_LIST_RE.search(date_el.get_text(strip=True))
        published_at = None
        if date_match:
            d, m, y, hh, mm = date_match.groups()
            published_at = f"{y}-{m}-{d}T{hh}:{mm}:00"

        district = None
        cat = li.select_one(".category")
        if cat:
            raw = cat.get_text(strip=True)
            district = raw.replace("Ereignisort:", "").strip() or None

        url = absolute_url(href)
        year_match = re.search(r"/polizeimeldungen/(\d{4})/", url)
        source_year = int(year_match.group(1)) if year_match else None

        items.append(
            {
                "id": article_id,
                "url": url,
                "title": link_el.get_text(strip=True),
                "published_at": published_at,
                "district": district,
                "source_year": source_year,
            }
        )

    next_url = None
    nav = soup.select_one("nav.pagination")
    if nav:
        next_link = nav.select_one("li.pager-item-next a[href]")
        if next_link and next_link.get("href"):
            next_url = absolute_url(next_link["href"].split("#")[0])

    return items, next_url


def pagination_param_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("nav.pagination a[href*='page_at_']"):
        href = a.get("href", "")
        match = re.search(r"(page_at_\d+_\d+)=", href)
        if match:
            return match.group(1)
    return None


def last_page_number(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    last = 1
    for a in soup.select("nav.pagination a[href*='page_at_']"):
        href = a.get("href", "")
        match = re.search(r"page_at_\d+_\d+=(\d+)", href)
        if match:
            last = max(last, int(match.group(1)))
    counter = soup.select_one("li.mobile-counter span")
    if counter and "/" in counter.get_text():
        try:
            last = max(last, int(counter.get_text().split("/")[-1].strip()))
        except ValueError:
            pass
    return last


def build_page_url(base_list_url: str, page_param: str, page_num: int) -> str:
    sep = "&" if "?" in base_list_url else "?"
    return f"{base_list_url}{sep}{page_param}={page_num}"


def _article_section(soup: BeautifulSoup):
    return soup.select_one(
        "#layout-grid__area--maincontent section.modul-text_bild"
    )


def _parse_images(article_section) -> list[dict]:
    images: list[dict] = []
    if not article_section:
        return images
    for img in article_section.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        lower = src.lower()
        if any(x in lower for x in ("polizeistern", "favicon", "logo", "sitelogo")):
            continue
        images.append(
            {
                "src": absolute_url(src),
                "alt": (img.get("alt") or "").strip(),
            }
        )
    return images


def parse_article_page(html: str, url: str, teaser: dict | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article_id = article_id_from_url(url)
    if not article_id:
        raise ValueError(f"Keine Artikel-ID in URL: {url}")

    title = None
    meta_title = soup.find("meta", attrs={"name": "dcterms.title"})
    if meta_title and meta_title.get("content"):
        title = meta_title["content"].strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""

    summary = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        summary = meta_desc["content"].strip()

    keywords_raw = ""
    meta_kw = soup.find("meta", attrs={"name": "keywords"})
    if meta_kw and meta_kw.get("content"):
        keywords_raw = meta_kw["content"].strip()
    tags = parse_tags_from_keywords(keywords_raw)

    meldung_date = None
    for p in soup.select("p.polizeimeldung"):
        text = p.get_text(strip=True)
        dm = DATE_MELDUNG_RE.search(text)
        if dm:
            d, m, y = dm.groups()
            meldung_date = f"{y}-{m}-{d}"
            break

    district = teaser.get("district") if teaser else None
    if not district:
        for p in soup.select("p.polizeimeldung[title='Ereignisort']"):
            district = p.get_text(strip=True)
            break

    article_section = _article_section(soup)
    body_text = None
    case_number = None
    if article_section:
        textile = article_section.select_one(".textile")
        if textile:
            body_text = textile.get_text("\n", strip=True) or None
        if body_text:
            nr = CASE_NUMBER_RE.search(body_text)
            if nr:
                case_number = nr.group(1)

    images = _parse_images(article_section)

    published_at = teaser.get("published_at") if teaser else None
    meta_sub = soup.find("meta", attrs={"name": "dcterms.submitted"})
    if meta_sub and meta_sub.get("content") and not published_at:
        published_at = f"{meta_sub['content']}T12:00:00"

    year_match = re.search(r"/polizeimeldungen/(\d{4})/", url)
    source_year = int(year_match.group(1)) if year_match else None

    return {
        "id": article_id,
        "url": url,
        "title": title or (teaser or {}).get("title", ""),
        "published_at": published_at,
        "meldung_date": meldung_date,
        "district": district,
        "summary": summary,
        "tags": tags,
        "case_number": case_number,
        "body_text": body_text,
        "images": images,
        "source_year": source_year,
    }


def tags_to_json(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    return json.dumps(tags, ensure_ascii=False)


def images_to_json(images: list[dict] | None) -> str | None:
    if not images:
        return None
    return json.dumps(images, ensure_ascii=False)


def tags_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def images_from_json(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []
