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


@router.post("/create-from-template")
async def notion_create_from_template(
    body: NotionFromTemplateRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    settings = get_settings()
    if not settings.notion_api_key:
        raise HTTPException(status_code=500, detail="NOTION_API_KEY not configured on server")

    try:
        result = await create_page_from_template(
            api_key=settings.notion_api_key,
            database_id=body.database_id,
            template_page_id=body.template_page_id,
            title=body.title,
            status_property=body.status_property,
            status_value=body.status_value,
            linked_sub_templates=[s.model_dump() for s in body.linked_sub_templates]
            if body.linked_sub_templates
            else None,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
