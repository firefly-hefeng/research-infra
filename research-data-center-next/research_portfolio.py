"""Validated public projection of the manually reviewed research portfolio."""
import hashlib
from pathlib import Path
import re

from platform_data import read_public_json, safe_url

MAX_TEXT = 3000
PATH = re.compile(r"/data/users/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.|｜-]+)+")
DOWNLOAD = re.compile(r"/research-code/[a-z0-9-]+-code\.zip")
LOGO = re.compile(r"/research-assets/[a-z0-9-]+\.png")
DIGEST = re.compile(r"[0-9a-f]{64}")


def text(value, limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("invalid_research_text")
    return value


def server_path(value):
    value = text(value, 1000)
    if not PATH.fullmatch(value) or ".." in value:
        raise ValueError("invalid_research_path")
    return value


def entries(value, maximum=20, empty=False):
    if not isinstance(value, list) or len(value) > maximum or not empty and not value:
        raise ValueError("invalid_research_entries")
    return value


def strings(value, maximum=12):
    return [text(item, 800) for item in entries(value, maximum)]


def web_url(value):
    result = safe_url(text(value, 1000))
    if result is None:
        raise ValueError("invalid_research_url")
    return result


def metric(row):
    if not isinstance(row, dict):
        raise ValueError("invalid_research_metric")
    return {"label": text(row.get("label"), 100), "display": text(row.get("display"), 100),
            "scope": text(row.get("scope"), 500)}


def artifact(row):
    if not isinstance(row, dict):
        raise ValueError("invalid_research_artifact")
    return {"label": text(row.get("label"), 200), "path": server_path(row.get("path"))}


def interface(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_interface")
    return {key: text(raw.get(key)) for key in ("availability", "input", "output", "entrypoint", "notes")}


def code(raw, root):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_code")
    url = text(raw.get("url"), 200)
    if not DOWNLOAD.fullmatch(url):
        raise ValueError("invalid_research_download")
    digest = text(raw.get("sha256"), 64)
    size = raw.get("bytes")
    if not DIGEST.fullmatch(digest) or type(size) is not int or not 1 <= size <= 20 * 1024 * 1024:
        raise ValueError("invalid_research_code_manifest")
    archive = root / "static" / url.removeprefix("/")
    if not archive.is_file() or archive.is_symlink() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest or archive.stat().st_size != size:
        raise ValueError("research_code_mismatch")
    return {"label": text(raw.get("label"), 200), "url": url, "sha256": digest, "bytes": size}


def effect(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_effect")
    return {"label": text(raw.get("label"), 200), "detail": text(raw.get("detail")), "evidence": text(raw.get("evidence"), 500)}


def partner_role(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_partner_role")
    return {"organization": text(raw.get("organization"), 300), "role": text(raw.get("role"), 200),
            "detail": text(raw.get("detail"))}


def outcome(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_outcome")
    return {"label": text(raw.get("label"), 200), "detail": text(raw.get("detail")), "status": text(raw.get("status"), 100)}


def report(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_report")
    return {
        "question": text(raw.get("question")), "methods": strings(raw.get("methods"), 8),
        "core_effects": [effect(row) for row in entries(raw.get("core_effects"), 8, empty=True)],
        "contributions": strings(raw.get("contributions"), 8),
        "partner_roles": [partner_role(row) for row in entries(raw.get("partner_roles"), 10)],
        "outcomes": [outcome(row) for row in entries(raw.get("outcomes"), 10)],
        "limitations": text(raw.get("limitations")), "next_step": text(raw.get("next_step")),
    }


def model(raw, root):
    if not isinstance(raw, dict) or raw.get("status") not in ("validated", "development"):
        raise ValueError("invalid_research_model")
    return {
        "id": text(raw.get("id"), 100), "name": text(raw.get("name"), 200),
        "task": text(raw.get("task"), 300), "status": raw["status"],
        "status_label": text(raw.get("status_label"), 100), "recommended": raw.get("recommended") is True,
        "summary": text(raw.get("summary")), "report": report(raw.get("report")),
        "metrics": [metric(row) for row in entries(raw.get("metrics"), 8)],
        "validation": text(raw.get("validation")),
        "artifact_paths": [artifact(row) for row in entries(raw.get("artifact_paths"), 12)],
        "components": strings(raw.get("components")), "interface": interface(raw.get("interface")),
        "code": code(raw.get("code"), root),
    }


def milestone(raw):
    if not isinstance(raw, dict) or raw.get("state") not in ("done", "blocked", "planned"):
        raise ValueError("invalid_research_milestone")
    return {"label": text(raw.get("label"), 200), "state": raw["state"], "detail": text(raw.get("detail"))}


def track(raw):
    if not isinstance(raw, dict) or raw.get("status") not in ("candidate", "research_plan"):
        raise ValueError("invalid_research_track")
    return {
        "id": text(raw.get("id"), 100), "name": text(raw.get("name"), 200), "status": raw["status"],
        "status_label": text(raw.get("status_label"), 100), "summary": text(raw.get("summary")),
        "report": report(raw.get("report")), "path": server_path(raw.get("path")), "next_step": text(raw.get("next_step")),
        "milestones": [milestone(row) for row in entries(raw.get("milestones"), 12)],
    }


def brand(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_brand")
    websites = []
    for row in entries(raw.get("websites"), 6):
        if not isinstance(row, dict):
            raise ValueError("invalid_research_website")
        websites.append({"label": text(row.get("label"), 100), "url": web_url(row.get("url"))})
    return {"name": text(raw.get("name"), 200), "product": text(raw.get("product"), 200),
            "statement": text(raw.get("statement")), "websites": websites}


def impact(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_impact")
    return {"value": text(raw.get("value"), 100), "label": text(raw.get("label"), 200),
            "scope": text(raw.get("scope"), 500), "kind": text(raw.get("kind"), 100)}


def partner(raw, root, assets):
    if not isinstance(raw, dict) or raw.get("category") not in ("ethics", "clinical", "hongkong", "academic"):
        raise ValueError("invalid_research_partner")
    logo = text(raw.get("logo"), 200)
    if not LOGO.fullmatch(logo):
        raise ValueError("invalid_research_logo")
    filename = logo.rsplit("/", 1)[-1]
    evidence = assets.get(filename)
    if evidence is None:
        raise ValueError("research_logo_not_in_manifest")
    image = root / "static" / logo.removeprefix("/")
    if not image.is_file() or image.is_symlink() or image.stat().st_size != evidence.get("bytes") or hashlib.sha256(image.read_bytes()).hexdigest() != evidence.get("sha256"):
        raise ValueError("research_logo_mismatch")
    return {"id": text(raw.get("id"), 100), "name": text(raw.get("name"), 300), "category": raw["category"],
            "relationship": text(raw.get("relationship"), 300), "logo": logo,
            "official_url": web_url(raw.get("official_url")), "note": text(raw.get("note"), 1000)}


def source(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_research_source")
    result = {"label": text(raw.get("label"), 200), "detail": text(raw.get("detail"), 1000)}
    if raw.get("url") is not None:
        result["url"] = web_url(raw["url"])
    return result


def research_portfolio(root):
    root = Path(root).resolve()
    raw = read_public_json(root, "data/research-portfolio.json")
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("invalid_research_portfolio")
    asset_document = read_public_json(root, "static/research-assets/manifest.json") or {}
    assets = {row.get("file"): row for row in asset_document.get("assets", []) if isinstance(row, dict) and isinstance(row.get("file"), str)}
    comparison = raw.get("comparison")
    if not isinstance(comparison, dict):
        raise ValueError("invalid_research_comparison")
    rows = []
    for row in entries(comparison.get("rows"), 8):
        if not isinstance(row, dict) or type(row.get("value")) not in (int, float) or row["value"] < 0:
            raise ValueError("invalid_research_comparison_row")
        rows.append({"label": text(row.get("label"), 200), "value": row["value"],
                     "display": text(row.get("display"), 100), "primary": row.get("primary") is True})
    models = [model(row, root) for row in entries(raw.get("models"), 12)]
    tracks = [track(row) for row in entries(raw.get("research_tracks"), 12)]
    partners = [partner(row, root, assets) for row in entries(raw.get("partners"), 30)]
    identities = [row["id"] for row in models + tracks + partners]
    if len(set(identities)) != len(identities) or sum(row["recommended"] for row in models) != 1:
        raise ValueError("invalid_research_identity")
    return {
        "schema_version": "1.0", "reviewed_at": text(raw.get("reviewed_at"), 10),
        "title": text(raw.get("title"), 200), "summary": text(raw.get("summary")), "brand": brand(raw.get("brand")),
        "common_root": server_path(raw.get("common_root")), "notes": strings(raw.get("notes"), 8),
        "impact": [impact(row) for row in entries(raw.get("impact"), 12)],
        "comparison": {"title": text(comparison.get("title"), 300), "metric": text(comparison.get("metric"), 100),
                       "direction": text(comparison.get("direction"), 100), "scope": text(comparison.get("scope"), 500), "rows": rows},
        "models": models, "research_tracks": tracks, "partners": partners,
        "sources": [source(row) for row in entries(raw.get("sources"), 12)],
        "capabilities": {"live_inference": False, "real_time_training_monitor": False, "code_download": True},
    }
