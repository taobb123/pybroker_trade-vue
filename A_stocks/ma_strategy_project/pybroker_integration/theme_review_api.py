# -*- coding: utf-8 -*-
"""题材复盘 API。不注册进日常工作流步骤，不改观察池。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from theme_review import list_concepts_live, review_themes_live

router = APIRouter(prefix="/api/theme-review", tags=["theme-review"])


class ThemeReviewBody(BaseModel):
    themes: str = Field(default="")


@router.get("/concepts")
def theme_concepts() -> dict:
    return list_concepts_live()


@router.post("")
def run_theme_review(body: ThemeReviewBody | None = None) -> dict:
    params = body or ThemeReviewBody()
    return review_themes_live(params.themes)
