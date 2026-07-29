from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(slots=True)
class SitePage:
    slug: str
    title: str
    meta_description: str
    body_markdown: str


def _parse_page(path: Path) -> SitePage:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = raw

    match = _FRONT_MATTER_RE.match(raw)
    if match:
        header, body = match.group(1), match.group(2)
        loaded = yaml.safe_load(header) or {}
        if isinstance(loaded, dict):
            meta = loaded

    slug = path.stem
    title = str(meta.get("title") or slug.replace("-", " ").title())
    meta_description = str(meta.get("meta_description") or "")
    return SitePage(
        slug=slug,
        title=title,
        meta_description=meta_description,
        body_markdown=body,
    )


def _render_markdown(markdown_text: str) -> str:
    try:
        import markdown
    except ImportError as exc:  # pragma: no cover - dependency/environment dependent
        raise RuntimeError(
            "Site build requires optional dependency 'markdown'. Install with: pip install toolgauntlet[site]"
        ) from exc

    return markdown.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "toc"],
        output_format="html5",
    )


def _render_nav(pages: list[SitePage], current_slug: str) -> str:
    links: list[str] = []
    for page in pages:
        active = " class=\"active\"" if page.slug == current_slug else ""
        links.append(f"<a href=\"./{page.slug}.html\"{active}>{html.escape(page.title)}</a>")
    return "".join(links)


def _render_html_document(*, site_title: str, page: SitePage, nav_html: str, content_html: str) -> str:
    title = page.title
    full_title = f"{title} | {site_title}" if site_title not in title else title
    meta_description = html.escape(page.meta_description)

    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        f"  <title>{html.escape(full_title)}</title>\n"
        f"  <meta name=\"description\" content=\"{meta_description}\" />\n"
        "  <link rel=\"stylesheet\" href=\"./assets/styles.css\" />\n"
        "</head>\n"
        "<body>\n"
        "  <header class=\"site-header\">\n"
        f"    <h1>{html.escape(site_title)}</h1>\n"
        "    <nav class=\"site-nav\">\n"
        f"      {nav_html}\n"
        "    </nav>\n"
        "  </header>\n"
        "  <main class=\"site-main\">\n"
        f"    {content_html}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _write_stylesheet(output_root: Path) -> None:
    assets = output_root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "styles.css").write_text(
        (
            ":root { color-scheme: light; }\n"
            "body { font-family: 'Segoe UI', system-ui, sans-serif; margin: 0; color: #111; background: linear-gradient(180deg,#f7f8fb 0%,#ffffff 100%); }\n"
            ".site-header { padding: 28px 24px 12px; border-bottom: 1px solid #e5e7eb; background: rgba(255,255,255,0.85); position: sticky; top: 0; backdrop-filter: blur(4px); }\n"
            ".site-header h1 { margin: 0 0 12px; font-size: 24px; letter-spacing: 0.2px; }\n"
            ".site-nav { display: flex; flex-wrap: wrap; gap: 8px; }\n"
            ".site-nav a { text-decoration: none; color: #1f2937; border: 1px solid #d1d5db; padding: 6px 10px; border-radius: 999px; font-size: 14px; }\n"
            ".site-nav a.active { background: #111827; color: #fff; border-color: #111827; }\n"
            ".site-main { max-width: 860px; margin: 0 auto; padding: 28px 20px 60px; line-height: 1.6; }\n"
            "h1,h2,h3 { line-height: 1.25; }\n"
            "code { background: #f3f4f6; padding: 1px 5px; border-radius: 4px; }\n"
            "pre { background: #0f172a; color: #e5e7eb; padding: 14px; overflow-x: auto; border-radius: 8px; }\n"
            "pre code { background: transparent; padding: 0; }\n"
            "table { border-collapse: collapse; width: 100%; }\n"
            "th,td { border: 1px solid #d1d5db; padding: 8px; text-align: left; }\n"
            "@media (max-width: 700px) { .site-header { position: static; } .site-main { padding-top: 20px; } }\n"
        ),
        encoding="utf-8",
    )


def build_site(
    *,
    pages_root: str | Path,
    output_root: str | Path,
    site_title: str = "ToolGauntlet",
    home_slug: str = "home",
) -> list[Path]:
    src_root = Path(pages_root)
    out_root = Path(output_root)

    if not src_root.exists() or not src_root.is_dir():
        raise FileNotFoundError(f"Pages root not found: {src_root}")

    markdown_files = sorted(src_root.glob("*.md"))
    if not markdown_files:
        raise FileNotFoundError(f"No markdown pages found under: {src_root}")

    pages = [_parse_page(path) for path in markdown_files]
    pages_by_slug = {page.slug: page for page in pages}

    if home_slug not in pages_by_slug:
        home_slug = pages[0].slug

    out_root.mkdir(parents=True, exist_ok=True)
    _write_stylesheet(out_root)

    written: list[Path] = []
    for page in pages:
        nav_html = _render_nav(pages, current_slug=page.slug)
        content_html = _render_markdown(page.body_markdown)
        rendered = _render_html_document(
            site_title=site_title,
            page=page,
            nav_html=nav_html,
            content_html=content_html,
        )
        target = out_root / f"{page.slug}.html"
        target.write_text(rendered, encoding="utf-8")
        written.append(target)

    index_html = (
        "<!doctype html><html><head>"
        f"<meta http-equiv=\"refresh\" content=\"0; url=./{home_slug}.html\" />"
        "</head><body>"
        f"<a href=\"./{home_slug}.html\">Open site</a>"
        "</body></html>\n"
    )
    (out_root / "index.html").write_text(index_html, encoding="utf-8")
    written.append(out_root / "index.html")

    return written
