"""
Notion API service — duplication complète d'une page template.
Copie récursive de tous les blocs, y compris les fichiers hébergés par Notion
(re-téléchargés puis re-uploadés via l'API File Uploads).
"""

import httpx

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"

_EXCLUDED_TYPES = frozenset(
    {
        "unsupported",
        "child_page",
        "child_database",
        "synced_block",
        "template",
    }
)

_MEDIA_TYPES = frozenset({"image", "video", "audio", "file", "pdf"})


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _norm(page_id: str) -> str:
    return page_id.replace("-", "").lower()


# ── Rich text ──────────────────────────────────────────────────────────────────


def _clean_rich_text(rt: dict) -> dict:
    rt_type = rt.get("type", "text")

    if rt_type == "mention":
        return {"type": "mention", "mention": rt.get("mention", {})}

    if rt_type == "equation":
        return {"type": "equation", "equation": rt.get("equation", {"expression": ""})}

    text_obj: dict = {"content": rt.get("plain_text", "")}
    link = rt.get("text", {}).get("link")
    if link:
        text_obj["link"] = link

    result: dict = {"type": "text", "text": text_obj}
    annotations = rt.get("annotations")
    if annotations:
        result["annotations"] = annotations

    return result


def _replace_refs_in_rich_text(rich_text: list, replacements: dict) -> list:
    out = []
    for rt in rich_text:
        rt = dict(rt)
        if rt.get("type") == "mention":
            mention = rt.get("mention", {})
            if mention.get("type") == "page":
                old_id = _norm(mention["page"].get("id", ""))
                if old_id in replacements:
                    rt = {
                        "type": "mention",
                        "mention": {"type": "page", "page": {"id": replacements[old_id]}},
                    }
        out.append(rt)
    return out


def _replace_refs_in_blocks(blocks: list, replacements: dict) -> list:
    out = []
    for block in blocks:
        block = dict(block)
        block_type = block.get("type")

        if block_type == "link_to_page":
            content = dict(block.get("link_to_page", {}))
            if content.get("type") == "page_id":
                old_id = _norm(content.get("page_id", ""))
                if old_id in replacements:
                    content["page_id"] = replacements[old_id]
                    block["link_to_page"] = content

        elif block_type:
            content = dict(block.get(block_type) or {})
            if "rich_text" in content:
                content["rich_text"] = _replace_refs_in_rich_text(
                    content["rich_text"], replacements
                )
            if "children" in content:
                content["children"] = _replace_refs_in_blocks(content["children"], replacements)
            block[block_type] = content

        out.append(block)
    return out


# ── File upload (pour copier les fichiers hébergés par Notion) ─────────────────


async def _reupload_notion_file(
    file_url: str,
    api_key: str,
    client: httpx.AsyncClient,
) -> str | None:
    """
    Télécharge un fichier hébergé par Notion (URL S3 temporaire)
    et le re-uploade via l'API Notion File Uploads.
    Retourne l'upload ID ou None si échec.
    """
    notion_hdrs = _headers(api_key)

    try:
        # 1. Créer une session d'upload
        create_resp = await client.post(
            f"{BASE_URL}/file_uploads",
            headers=notion_hdrs,
            json={"mode": "single_part"},
        )
        if not create_resp.is_success:
            return None

        upload_data = create_resp.json()
        upload_id: str = upload_data["id"]
        upload_url: str = upload_data.get("upload_url", "")
        if not upload_url:
            return None

        # 2. Télécharger le fichier original (URL S3 pre-signed)
        file_resp = await client.get(file_url)
        if not file_resp.is_success:
            return None

        content_type = file_resp.headers.get("content-type", "application/octet-stream")
        filename = file_url.split("?")[0].rsplit("/", 1)[-1] or "file"

        # 3. Uploader vers Notion (multipart form-data)
        upload_resp = await client.post(
            upload_url,
            headers={"Authorization": f"Bearer {api_key}", "Notion-Version": NOTION_VERSION},
            files={"file": (filename, file_resp.content, content_type)},
        )
        if not upload_resp.is_success:
            return None

        return upload_id

    except Exception:
        return None


# ── Nettoyage des blocs ────────────────────────────────────────────────────────


async def _clean_media_block(
    block_type: str,
    content: dict,
    api_key: str,
    client: httpx.AsyncClient,
) -> dict | None:
    """
    Gère les blocs média :
    - external → préservé tel quel
    - file (Notion-hébergé) → re-uploadé via File Uploads API
    """
    media_type = content.get("type")

    if media_type == "external":
        url = content.get("external", {}).get("url", "")
        if url:
            return {"type": block_type, block_type: {"type": "external", "external": {"url": url}}}

    elif media_type == "file":
        url = content.get("file", {}).get("url", "")
        if url:
            upload_id = await _reupload_notion_file(url, api_key, client)
            if upload_id:
                return {
                    "type": block_type,
                    block_type: {"type": "file_upload", "file_upload": {"id": upload_id}},
                }

    return None


def _clean_block_sync(block: dict) -> dict | None:
    """Nettoyage synchrone pour les blocs non-média."""
    block_type = block.get("type")
    if not block_type or block_type in _EXCLUDED_TYPES or block_type in _MEDIA_TYPES:
        return None

    content = dict(block.get(block_type) or {})
    for field in (
        "created_time",
        "last_edited_time",
        "has_children",
        "created_by",
        "last_edited_by",
    ):
        content.pop(field, None)

    # Notion refuse null — on supprime tous les champs à None
    content = {k: v for k, v in content.items() if v is not None}

    if "rich_text" in content:
        content["rich_text"] = [_clean_rich_text(rt) for rt in content["rich_text"]]

    return {"type": block_type, block_type: content}


# ── Récupération récursive ─────────────────────────────────────────────────────


async def _fetch_blocks_recursive(
    block_id: str,
    headers: dict,
    client: httpx.AsyncClient,
    api_key: str,
) -> list[dict]:
    """Récupère tous les blocs, y compris les enfants imbriqués et les fichiers."""
    blocks: list[dict] = []
    cursor: str | None = None

    while True:
        url = f"{BASE_URL}/blocks/{block_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"

        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        for block in data.get("results", []):
            block_type = block.get("type")

            if block_type in _MEDIA_TYPES:
                cleaned = await _clean_media_block(
                    block_type, block.get(block_type) or {}, api_key, client
                )
            else:
                cleaned = _clean_block_sync(block)

            if cleaned:
                if block.get("has_children"):
                    children = await _fetch_blocks_recursive(block["id"], headers, client, api_key)
                    if children:
                        cleaned[cleaned["type"]]["children"] = children
                blocks.append(cleaned)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return blocks


# ── Utilitaires ────────────────────────────────────────────────────────────────


async def _get_title_property_name(
    database_id: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> str:
    resp = await client.get(f"{BASE_URL}/databases/{database_id}", headers=headers)
    resp.raise_for_status()
    db = resp.json()
    for name, prop in db.get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    return "Name"


async def _create_sub_page_from_template(
    parent_page_id: str,
    template_id: str,
    title: str,
    api_key: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> str:
    resp = await client.post(
        f"{BASE_URL}/pages",
        headers=headers,
        json={
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
        },
    )
    resp.raise_for_status()
    sub_page_id = resp.json()["id"]

    template_blocks = await _fetch_blocks_recursive(template_id, headers, client, api_key)
    for i in range(0, len(template_blocks), 100):
        patch_resp = await client.patch(
            f"{BASE_URL}/blocks/{sub_page_id}/children",
            headers=headers,
            json={"children": template_blocks[i : i + 100]},
        )
        if not patch_resp.is_success:
            raise ValueError(
                f"Notion PATCH blocks failed [{patch_resp.status_code}]: {patch_resp.text}"
            )

    return sub_page_id


# ── Point d'entrée principal ───────────────────────────────────────────────────


async def create_page_from_template(
    api_key: str,
    database_id: str,
    template_page_id: str,
    title: str,
    status_property: str | None = None,
    status_value: str = "Not Started",
    linked_sub_templates: list[dict] | None = None,
) -> dict:
    """
    Crée une page dans une base Notion en dupliquant un template.
    Copie récursive de tous les blocs, y compris les fichiers hébergés par Notion.
    """
    hdrs = _headers(api_key)

    async with httpx.AsyncClient(timeout=180.0) as client:
        title_prop = await _get_title_property_name(database_id, hdrs, client)

        template_blocks = await _fetch_blocks_recursive(template_page_id, hdrs, client, api_key)

        properties: dict = {title_prop: {"title": [{"text": {"content": title}}]}}
        if status_property:
            properties[status_property] = {"status": {"name": status_value}}

        create_resp = await client.post(
            f"{BASE_URL}/pages",
            headers=hdrs,
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        create_resp.raise_for_status()
        new_page = create_resp.json()
        page_id = new_page["id"]

        # Créer les sous-pages liées et construire la table de remplacement
        replacements: dict[str, str] = {}
        sub_pages_created: list[dict] = []

        for sub in linked_sub_templates or []:
            old_template_id = _norm(sub["template_id"])
            sub_title = sub.get("title") or title
            new_sub_id = await _create_sub_page_from_template(
                parent_page_id=page_id,
                template_id=sub["template_id"],
                title=sub_title,
                api_key=api_key,
                headers=hdrs,
                client=client,
            )
            replacements[old_template_id] = new_sub_id
            sub_pages_created.append({"template_id": sub["template_id"], "new_page_id": new_sub_id})

        if replacements:
            template_blocks = _replace_refs_in_blocks(template_blocks, replacements)

        for i in range(0, len(template_blocks), 100):
            patch_resp = await client.patch(
                f"{BASE_URL}/blocks/{page_id}/children",
                headers=hdrs,
                json={"children": template_blocks[i : i + 100]},
            )
            if not patch_resp.is_success:
                raise ValueError(
                    f"Notion PATCH blocks failed [{patch_resp.status_code}]: {patch_resp.text}"
                )

    return {
        "page_id": page_id,
        "url": new_page.get("url", ""),
        "blocks_copied": len(template_blocks),
        "title": title,
        "sub_pages": sub_pages_created,
    }
