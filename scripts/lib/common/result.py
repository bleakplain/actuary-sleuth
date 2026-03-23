#!/usr/bin/env python3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProcessResult:
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_type: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def get_or_raise(self, key: str) -> Any:
        if key not in self.data:
            raise KeyError(f"Missing required key: {key}")
        return self.data[key]

    @classmethod
    def success_result(cls, data: Dict[str, Any]) -> 'ProcessResult':
        return cls(success=True, data=data)

    @classmethod
    def error_result(cls, error: str, error_type: str = "ProcessingError") -> 'ProcessResult':
        return cls(success=False, data={}, error=error, error_type=error_type)

    @classmethod
    def from_dict(cls, result_dict: Dict[str, Any]) -> 'ProcessResult':
        return cls(
            success=result_dict.get('success', False),
            data={k: v for k, v in result_dict.items() if k not in ('success', 'error', 'error_type')},
            error=result_dict.get('error', ''),
            error_type=result_dict.get('error_type', '')
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {'success': self.success}
        if self.success:
            result.update(self.data)
        else:
            result['error'] = self.error
            result['error_type'] = self.error_type
        return result
