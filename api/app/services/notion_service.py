"""
Notion API service — création de page depuis un template.
Copie récursive de tous les blocs (nesting inclus).
Les sous-pages liées (ex: tableau de bord) sont créées en tant que sub-pages
de la page principale, et les références dans les blocs sont remplacées.
"""

import httpx

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _norm(page_id: str) -> str:
    """Normalise un ID Notion (supprime les tirets pour comparer)."""
    return page_id.replace("-", "").lower()


def _clean_rich_text(rt: dict) -> dict:
    """Préserve mentions, hyperliens et formatage."""
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
    """Remplace les mentions de page dans le rich_text."""
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
    """Remplace récursivement tous les liens/mentions vers les IDs originaux."""
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


_EXCLUDED_TYPES = frozenset(
    {
        "unsupported",
        "child_page",
        "child_database",
        "synced_block",  # blocs synchronisés — non créables via API
        "template",  # boutons template Notion
    }
)


_MEDIA_TYPES = frozenset({"image", "video", "audio", "file", "pdf"})


def _clean_media_block(block_type: str, content: dict) -> dict | None:
    """
    Blocs média : seul le sous-type 'external' peut être recréé via API.
    Les fichiers Notion-hébergés ('file') ont des URLs expirables — on les ignore.
    """
    media_type = content.get("type")
    if media_type == "external":
        url = content.get("external", {}).get("url", "")
        if url:
            return {"type": block_type, block_type: {"type": "external", "external": {"url": url}}}
    return None


def _clean_block(block: dict) -> dict | None:
    """Supprime les champs read-only d'un bloc Notion pour pouvoir le recréer."""
    block_type = block.get("type")
    if not block_type or block_type in _EXCLUDED_TYPES:
        return None

    content = dict(block.get(block_type) or {})

    if block_type in _MEDIA_TYPES:
        return _clean_media_block(block_type, content)

    for field in (
        "created_time",
        "last_edited_time",
        "has_children",
        "created_by",
        "last_edited_by",
    ):
        content.pop(field, None)

    if "rich_text" in content:
        content["rich_text"] = [_clean_rich_text(rt) for rt in content["rich_text"]]

    return {"type": block_type, block_type: content}


async def _fetch_blocks_recursive(
    block_id: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> list[dict]:
    """Récupère tous les blocs d'une page, y compris les enfants imbriqués."""
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
            cleaned = _clean_block(block)
            if cleaned:
                if block.get("has_children"):
                    children = await _fetch_blocks_recursive(block["id"], headers, client)
                    if children:
                        cleaned[cleaned["type"]]["children"] = children
                blocks.append(cleaned)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return blocks


async def _get_title_property_name(
    database_id: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> str:
    """Retourne le nom de la propriété titre de la base de données."""
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
    headers: dict,
    client: httpx.AsyncClient,
) -> str:
    """
    Crée une sous-page dans parent_page_id depuis le template donné.
    Retourne l'ID de la nouvelle sous-page.
    """
    # Créer la sous-page vide
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

    # Copier les blocs du template
    template_blocks = await _fetch_blocks_recursive(template_id, headers, client)
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

    linked_sub_templates : liste de sous-pages à créer et à lier automatiquement.
    Format : [{"template_id": "xxx", "title": "Tableau de bord — Client"}]
    Les références dans les blocs du template principal sont remplacées par les
    IDs des nouvelles sous-pages créées.
    """
    hdrs = _headers(api_key)

    async with httpx.AsyncClient(timeout=120.0) as client:
        # 1. Nom exact de la propriété titre
        title_prop = await _get_title_property_name(database_id, hdrs, client)

        # 2. Récupérer les blocs du template principal (récursivement)
        template_blocks = await _fetch_blocks_recursive(template_page_id, hdrs, client)

        # 3. Construire les propriétés
        properties: dict = {title_prop: {"title": [{"text": {"content": title}}]}}
        if status_property:
            properties[status_property] = {"status": {"name": status_value}}

        # 4. Créer la page principale (vide)
        create_resp = await client.post(
            f"{BASE_URL}/pages",
            headers=hdrs,
            json={"parent": {"database_id": database_id}, "properties": properties},
        )
        create_resp.raise_for_status()
        new_page = create_resp.json()
        page_id = new_page["id"]

        # 5. Créer les sous-pages liées et construire la table de remplacement
        replacements: dict[str, str] = {}
        sub_pages_created: list[dict] = []

        for sub in linked_sub_templates or []:
            old_template_id = _norm(sub["template_id"])
            sub_title = sub.get("title") or title
            new_sub_id = await _create_sub_page_from_template(
                parent_page_id=page_id,
                template_id=sub["template_id"],
                title=sub_title,
                headers=hdrs,
                client=client,
            )
            replacements[old_template_id] = new_sub_id
            sub_pages_created.append({"template_id": sub["template_id"], "new_page_id": new_sub_id})

        # 6. Remplacer les références dans les blocs du template principal
        if replacements:
            template_blocks = _replace_refs_in_blocks(template_blocks, replacements)

        # 7. Injecter les blocs dans la page principale par chunks de 100
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
