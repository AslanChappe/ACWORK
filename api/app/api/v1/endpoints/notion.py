from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import verify_api_key
from app.services.notion_service import create_page_from_template

router = APIRouter()


class LinkedSubTemplate(BaseModel):
    template_id: str
    title: str | None = None


class NotionFromTemplateRequest(BaseModel):
    database_id: str
    template_page_id: str
    title: str
    status_property: str | None = None
    status_value: str = "Not Started"
    linked_sub_templates: list[LinkedSubTemplate] | None = None
    call_blocks: list[dict] | None = None
    notion_api_key: str | None = None  # clé spécifique au client (prioritaire sur l'env)


@router.post("/create-from-template")
async def notion_create_from_template(
    body: NotionFromTemplateRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    settings = get_settings()
    api_key = body.notion_api_key or settings.notion_api_key
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Notion API key missing: pass notion_api_key in body or set NOTION_API_KEY",
        )

    try:
        result = await create_page_from_template(
            api_key=api_key,
            database_id=body.database_id,
            template_page_id=body.template_page_id,
            title=body.title,
            status_property=body.status_property,
            status_value=body.status_value,
            linked_sub_templates=[s.model_dump() for s in body.linked_sub_templates]
            if body.linked_sub_templates
            else None,
            call_blocks=body.call_blocks,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
