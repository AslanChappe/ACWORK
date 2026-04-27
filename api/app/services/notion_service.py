"""
Notion API service — duplication complète d'une page template.

Utilise le paramètre natif `template` de POST /v1/pages (API 2026-03-11)
pour que Notion copie lui-même tout le contenu (images, blocs imbriqués…).
Le contenu étant rempli de manière asynchrone, on poll jusqu'à ce qu'il
apparaisse, puis on met à jour les liens internes et on ajoute les données
du call en bas de page.
"""

import asyncio

import httpx

NOTION_VERSION = "2026-03-11"
BASE_URL = "https://api.notion.com/v1"


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _norm(page_id: str) -> str:
    return page_id.replace("-", "").lower()


# ── Attente du remplissage asynchrone du template ─────────────────────────────


async def _wait_for_page_content(
    page_id: str,
    headers: dict,
    client: httpx.AsyncClient,
    max_seconds: int = 30,
) -> bool:
    """Poll jusqu'à ce que la page ait du contenu (remplissage async du template)."""
    for _ in range(max_seconds):
        resp = await client.get(
            f"{BASE_URL}/blocks/{page_id}/children?page_size=1",
            headers=headers,
        )
        if resp.is_success and resp.json().get("results"):
            return True
        await asyncio.sleep(1)
    return False


# ── Remplacement récursif des liens internes ──────────────────────────────────


async def _update_links_in_page(
    block_id: str,
    old_id_norm: str,
    new_page_id: str,
    headers: dict,
    client: httpx.AsyncClient,
) -> None:
    """
    Parcourt récursivement tous les blocs d'une page et remplace les références
    à old_id par new_page_id (link_to_page et @mention dans rich_text).
    """
    cursor: str | None = None

    while True:
        url = f"{BASE_URL}/blocks/{block_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"

        resp = await client.get(url, headers=headers)
        if not resp.is_success:
            break
        data = resp.json()

        for block in data.get("results", []):
            block_type = block.get("type")
            bid = block["id"]

            # Blocs link_to_page
            if block_type == "link_to_page":
                ltp = block.get("link_to_page", {})
                if ltp.get("type") == "page_id" and _norm(ltp.get("page_id", "")) == old_id_norm:
                    await client.patch(
                        f"{BASE_URL}/blocks/{bid}",
                        headers=headers,
                        json={"link_to_page": {"type": "page_id", "page_id": new_page_id}},
                    )

            # Blocs avec rich_text (mentions @page)
            elif block_type:
                content = block.get(block_type, {})
                rich_text = content.get("rich_text", [])
                updated_rt = []
                changed = False

                for rt in rich_text:
                    if rt.get("type") == "mention":
                        mention = rt.get("mention", {})
                        if (
                            mention.get("type") == "page"
                            and _norm(mention["page"].get("id", "")) == old_id_norm
                        ):
                            rt = {
                                "type": "mention",
                                "mention": {"type": "page", "page": {"id": new_page_id}},
                            }
                            changed = True
                    updated_rt.append(rt)

                if changed:
                    await client.patch(
                        f"{BASE_URL}/blocks/{bid}",
                        headers=headers,
                        json={block_type: {"rich_text": updated_rt}},
                    )

            # Récursion dans les enfants
            if block.get("has_children"):
                await _update_links_in_page(bid, old_id_norm, new_page_id, headers, client)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")


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


# ── Point d'entrée principal ───────────────────────────────────────────────────


async def create_page_from_template(
    api_key: str,
    database_id: str,
    template_page_id: str,
    title: str,
    status_property: str | None = None,
    status_value: str = "Not Started",
    linked_sub_templates: list[dict] | None = None,
    call_blocks: list[dict] | None = None,
) -> dict:
    """
    Crée une page dans une base Notion en dupliquant un template via
    le paramètre natif `template` (API 2026-03-11).

    Flux :
    1. POST /pages avec template_id → Notion copie tout en interne
    2. Poll jusqu'à ce que le contenu soit disponible
    3. Pour chaque sous-template (ex: tableau de bord) :
       a. Crée la sous-page avec template_id
       b. Poll jusqu'à disponibilité
       c. Remplace les liens vers le template original par la nouvelle sous-page
    4. PATCH pour ajouter les blocs supplémentaires (données du call)
    """
    hdrs = _headers(api_key)

    async with httpx.AsyncClient(timeout=180.0) as client:
        # 1. Nom exact de la propriété titre
        title_prop = await _get_title_property_name(database_id, hdrs, client)

        properties: dict = {title_prop: {"title": [{"text": {"content": title}}]}}
        if status_property:
            properties[status_property] = {"status": {"name": status_value}}

        # 2. Créer la page principale avec template_id
        create_resp = await client.post(
            f"{BASE_URL}/pages",
            headers=hdrs,
            json={
                "parent": {"database_id": database_id},
                "properties": properties,
                "template": {"type": "template_id", "template_id": template_page_id},
            },
        )
        if not create_resp.is_success:
            raise ValueError(
                f"Page creation failed [{create_resp.status_code}]: {create_resp.text}"
            )
        new_page = create_resp.json()
        page_id = new_page["id"]

        # 3. Attendre le remplissage asynchrone du template
        await _wait_for_page_content(page_id, hdrs, client)

        # 4. Créer les sous-pages liées et mettre à jour les liens internes
        sub_pages_created: list[dict] = []

        for sub in linked_sub_templates or []:
            sub_title = sub.get("title") or title
            old_id_norm = _norm(sub["template_id"])

            # Créer la sous-page avec template_id
            sub_resp = await client.post(
                f"{BASE_URL}/pages",
                headers=hdrs,
                json={
                    "parent": {"page_id": page_id},
                    "properties": {"title": {"title": [{"text": {"content": sub_title}}]}},
                    "template": {"type": "template_id", "template_id": sub["template_id"]},
                },
            )
            if not sub_resp.is_success:
                raise ValueError(
                    f"Sub-page creation failed [{sub_resp.status_code}]: {sub_resp.text}"
                )
            new_sub_id = sub_resp.json()["id"]

            # Attendre le remplissage
            await _wait_for_page_content(new_sub_id, hdrs, client)

            # Remplacer les références à l'ancien template par la nouvelle sous-page
            await _update_links_in_page(page_id, old_id_norm, new_sub_id, hdrs, client)

            sub_pages_created.append({"template_id": sub["template_id"], "new_page_id": new_sub_id})

        # 5. Ajouter les blocs supplémentaires en bas de page (données du call)
        if call_blocks:
            patch_resp = await client.patch(
                f"{BASE_URL}/blocks/{page_id}/children",
                headers=hdrs,
                json={"children": call_blocks},
            )
            if not patch_resp.is_success:
                raise ValueError(
                    f"Appending call blocks failed [{patch_resp.status_code}]: {patch_resp.text}"
                )

    return {
        "page_id": page_id,
        "url": new_page.get("url", ""),
        "title": title,
        "sub_pages": sub_pages_created,
    }
