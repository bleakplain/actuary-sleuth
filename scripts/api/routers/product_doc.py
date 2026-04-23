#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品文档解析结果 API"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.database import (
    save_parsed_document,
    get_parsed_document,
    list_parsed_documents,
    update_parsed_document_review,
)
from lib.doc_parser import parse_product_document

router = APIRouter(prefix="/api/product-docs", tags=["product-docs"])


class ParseRequest(BaseModel):
    file_path: str


class ReviewRequest(BaseModel):
    reviewer: str
    comment: Optional[str] = None
    status: str = "approved"


@router.post("/parse")
async def parse_document(request: ParseRequest):
    try:
        audit_doc = parse_product_document(request.file_path)
        doc_id = str(uuid.uuid4())
        doc = {
            "id": doc_id,
            "file_name": audit_doc.file_name,
            "file_path": request.file_path,
            "file_type": audit_doc.file_type,
            "clauses": [
                {"number": c.number, "title": c.title, "text": c.text}
                for c in audit_doc.clauses
            ],
            "premium_tables": [
                {"raw_text": t.raw_text, "data": t.data}
                for t in audit_doc.premium_tables
            ],
            "notices": [
                {"title": s.title, "content": s.content}
                for s in audit_doc.notices
            ],
            "health_disclosures": [
                {"title": s.title, "content": s.content}
                for s in audit_doc.health_disclosures
            ],
            "exclusions": [
                {"title": s.title, "content": s.content}
                for s in audit_doc.exclusions
            ],
            "rider_clauses": [
                {"number": c.number, "title": c.title, "text": c.text}
                for c in audit_doc.rider_clauses
            ],
            "raw_content": None,
            "parse_time": datetime.now(timezone.utc).isoformat(),
            "warnings": audit_doc.warnings,
        }
        save_parsed_document(doc)
        return {"id": doc_id, "status": "parsed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    doc = get_parsed_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("")
async def list_documents(
    review_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    docs = list_parsed_documents(review_status, limit, offset)
    return docs


@router.patch("/{doc_id}/review")
async def review_document(doc_id: str, request: ReviewRequest):
    doc = get_parsed_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    updated = update_parsed_document_review(
        doc_id, request.status, request.reviewer, request.comment
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Update failed")
    return {"id": doc_id, "status": request.status}
