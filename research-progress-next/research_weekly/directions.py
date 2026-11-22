"""Build the team's direction index from short, shared Markdown notes."""

import re

from .core import PROJECT, child, read_text


DIRECTION_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HEADINGS = {"研究问题": "question", "当前进展": "progress", "下一步": "next", "来源与范围": "evidence"}


def direction_roots(cfg):
    return (PROJECT / "deploy" / "directions", cfg["roots"]["team"] / "directions")


def read_direction(cfg, direction_id):
    """Prefer a team note, falling back to the bundled note for the same ID."""
    if not DIRECTION_ID.fullmatch(direction_id):
        raise FileNotFoundError(direction_id)
    for root in reversed(direction_roots(cfg)):
        path = child(root, direction_id + ".md")
        if path.is_file():
            break
    else:
        raise FileNotFoundError(direction_id)

    markdown = read_text(path, 64_000).replace("\r\n", "\n")
    title, _, body = markdown.strip().partition("\n")
    if not title.startswith("# ") or not title[2:].strip():
        raise ValueError("方向文档首行需为 # 标题")

    sections = re.split(r"(?m)^## ([^\n]+)\n", body)
    intro = sections[0]
    date = re.search(r"(?m)^核对日期[：:][ \t]*(\d{4}-\d{2}-\d{2})[ \t]*$", intro)
    lead = re.search(r"(?m)^负责人[：:][ \t]*(.+)$", intro)
    item = {
        "id": direction_id,
        "title": title[2:].strip(),
        "updated_at": date[1] if date else None,
        "lead": lead[1].strip() if lead else None,
        "markdown": markdown,
    }
    for heading, content in zip(sections[1::2], sections[2::2]):
        key = HEADINGS.get(heading.strip())
        if key:
            item[key] = content.strip()
    return item


def load_directions(cfg):
    """Return short cards and identify source notes that could not be read."""
    names = {path.stem for root in direction_roots(cfg) for path in root.glob("*.md")
             if DIRECTION_ID.fullmatch(path.stem)}
    items, unavailable = [], []
    for direction_id in sorted(names):
        try:
            item = read_direction(cfg, direction_id)
        except (OSError, ValueError):
            unavailable.append(direction_id)
            continue
        card = {key: value for key, value in item.items() if key != "markdown"}
        for key in HEADINGS.values():
            value = card.get(key, "")
            if len(value) > 500:
                card[key] = value[:500].rstrip() + "…"
        items.append(card)
    return sorted(items, key=lambda item: item["updated_at"] or "", reverse=True), unavailable
