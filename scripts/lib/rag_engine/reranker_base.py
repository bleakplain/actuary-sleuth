#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精排器抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseReranker(ABC):
    """精排器统一接口"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...
