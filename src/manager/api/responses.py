"""统一响应模型和异常处理器"""

import math
import traceback
from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from src.utils.logger import get_logger

# 泛型类型变量
T = TypeVar("T")

logger = get_logger(__name__)


def _convert_pydantic_to_dict(obj: Any) -> Any:
    """
    递归转换 Pydantic 模型为 dict

    Args:
        obj: 任意对象

    Returns:
        Any: 转换后的对象
    """
    from decimal import Decimal

    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, float):
        return obj if not math.isnan(obj) else None
    elif isinstance(obj, BaseModel):
        return _convert_pydantic_to_dict(obj.model_dump())
    elif isinstance(obj, list):
        return [_convert_pydantic_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: _convert_pydantic_to_dict(value) for key, value in obj.items()}
    else:
        return obj


class ApiResponse(BaseModel, Generic[T]):
    """统一API响应格式"""

    code: int = 0
    message: str = "success"
    data: Optional[T] = None

    class Config:
        json_schema_extra = {"example": {"code": 0, "message": "success", "data": {}}}


class ErrorResponse(BaseModel):
    """错误响应格式"""

    code: int = 9999
    message: str

    class Config:
        json_schema_extra = {"example": {"code": 9999, "message": "错误信息"}}


def success_response(data: Any = None, message: str = "success") -> JSONResponse:
    """
    成功响应包装

    Args:
        data: 响应数据
        message: 响应消息

    Returns:
        JSONResponse: 包装后的响应
    """
    # 自动转换 Pydantic 模型为 JSON 可序列化的 dict
    serialized_data = _convert_pydantic_to_dict(data)

    return JSONResponse(content={"code": 0, "message": message, "data": serialized_data})


def error_response(code: int = 9999, message: str = "操作失败") -> JSONResponse:
    """
    错误响应包装

    Args:
        code: 错误码，默认 9999
        message: 错误信息

    Returns:
        JSONResponse: 包装后的错误响应
    """
    return JSONResponse(content={"code": code, "message": message}, status_code=400)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常处理器

    拦截所有未捕获的异常并返回统一格式
    """
    from src.utils.logger import get_logger

    logger = get_logger(__name__)

    error_message = str(exc)
    traceback_str = traceback.format_exc()

    logger.error(f"未处理的异常: {error_message}\n{traceback_str}")
    return error_response(code=9999, message=error_message)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    HTTP异常处理器

    处理 FastAPI/Starlette HTTPException
    """
    logger.error(f"HTTP异常: {exc.status_code} - {exc.detail if exc.detail else '请求失败'}")
    return error_response(code=exc.status_code, message=exc.detail if exc.detail else "请求失败")


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    请求验证异常处理器

    处理 Pydantic 验证错误
    """
    error_details = exc.errors()
    error_messages = []

    for error in error_details:
        loc = " -> ".join(str(x) for x in error["loc"])
        msg = f"{loc}: {error['msg']}"
        error_messages.append(msg)
    logger.error(f"请求验证错误: {'; '.join(error_messages)}")
    return error_response(code=400, message="; ".join(error_messages))
