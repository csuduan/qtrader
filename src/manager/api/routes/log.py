"""
日志查看 API 路由

提供日志文件读取和列表功能，支持类似 tail -f 的实时查看效果
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query

from src.manager.api.responses import error_response, success_response
from src.utils.config_loader import get_config_loader
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/log", tags=["日志"])


def get_log_dir() -> Path:
    """获取日志目录"""
    app_config = get_config_loader()._load_app_config()
    log_dir = Path(app_config.paths.logs).expanduser().resolve()
    return log_dir


@router.get("")
async def get_log(
    account_id: str = Query(..., description="账户ID"),
    filename: str = Query("app", description="日志文件名（app 或 error）"),
    offset: int = Query(0, description="文件字节偏移量"),
    limit: int = Query(1000, description="最大行数"),
):
    """
    获取日志内容

    - **account_id**: 账户ID
    - **filename**: 日志文件名（app 或 error，默认为 app）
    - **offset**: 文件字节偏移量（从0开始），默认为0表示从文件末尾读取最近1000行
    - **limit**: 最大返回行数（默认1000）

    返回日志行列表、新的偏移量和是否还有更多内容
    """
    try:
        log_dir = get_log_dir()
        # 日志文件路径: logs/{account_id}/trader-{account_id}_{filename}.log
        log_file = log_dir / account_id / f"trader-{account_id}_{filename}.log"

        if not log_file.exists():
            # 尝试查找任何匹配的日志文件
            account_log_dir = log_dir / account_id
            if account_log_dir.exists():
                log_files = list(account_log_dir.glob(f"*{filename}*.log"))
                if log_files:
                    log_file = log_files[0]
                else:
                    return success_response(
                        data={"lines": [], "offset": 0, "has_more": False},
                        message="日志文件不存在"
                    )
            else:
                return success_response(
                    data={"lines": [], "offset": 0, "has_more": False},
                    message="日志目录不存在"
                )

        # 获取文件当前大小
        file_size = log_file.stat().st_size

        # 如果 offset 超过文件大小，说明文件被轮转或截断了，重置为0
        if offset > file_size:
            offset = 0

        lines: List[str] = []

        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            # 如果 offset 为 0 且文件较大，从文件末尾读取最近的内容
            if offset == 0 and file_size > 0:
                # 估算：平均每行约200字节，读取最近 limit 行的内容
                # 额外多读一些字节以确保能读到完整的 limit 行
                estimated_bytes = limit * 200
                start_pos = max(0, file_size - estimated_bytes)
                f.seek(start_pos)

                # 如果不在文件开头，跳过第一行（可能不完整）
                if start_pos > 0:
                    f.readline()

                # 读取所有剩余行
                all_lines = f.readlines()

                # 只保留最后 limit 行
                lines = [line.rstrip("\n") for line in all_lines[-limit:]]
                new_offset = file_size

                # 判断是否还有更多内容（前面还有）
                has_more = start_pos > 0
            else:
                # 正常从指定 offset 读取
                f.seek(offset)

                for _ in range(limit):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line.rstrip("\n"))

                new_offset = f.tell()

                # 判断是否还有更多内容
                has_more = bool(f.readline())

        return success_response(
            data={
                "lines": lines,
                "offset": new_offset,
                "has_more": has_more,
                "file_size": file_size,
            },
            message="获取成功"
        )

    except Exception as e:
        logger.exception(f"获取日志失败: {e}")
        return error_response(code=500, message=f"获取日志失败: {str(e)}")


@router.get("/files")
async def get_log_files(
    account_id: str = Query(..., description="账户ID"),
):
    """
    获取账户的日志文件列表

    - **account_id**: 账户ID

    返回可用的日志文件列表，包括文件名、大小和修改时间
    """
    try:
        log_dir = get_log_dir()
        account_log_dir = log_dir / account_id

        if not account_log_dir.exists():
            return success_response(data={"files": []}, message="日志目录不存在")

        files = []
        for log_file in sorted(account_log_dir.glob("*.log")):
            try:
                stat = log_file.stat()
                files.append({
                    "name": log_file.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except Exception as e:
                logger.warning(f"获取文件信息失败 {log_file}: {e}")

        return success_response(data={"files": files}, message="获取成功")

    except Exception as e:
        logger.exception(f"获取日志文件列表失败: {e}")
        return error_response(code=500, message=f"获取日志文件列表失败: {str(e)}")


@router.get("/download")
async def download_log(
    account_id: str = Query(..., description="账户ID"),
    filename: str = Query("app", description="日志文件名（app 或 error）"),
):
    """
    下载完整日志文件

    - **account_id**: 账户ID
    - **filename**: 日志文件名（app 或 error，默认为 app）

    返回日志文件内容
    """
    try:
        log_dir = get_log_dir()
        log_file = log_dir / account_id / f"trader-{account_id}_{filename}.log"

        if not log_file.exists():
            # 尝试查找任何匹配的日志文件
            account_log_dir = log_dir / account_id
            if account_log_dir.exists():
                log_files = list(account_log_dir.glob(f"*{filename}*.log"))
                if log_files:
                    log_file = log_files[0]

        if not log_file.exists():
            return error_response(code=404, message="日志文件不存在")

        # 读取文件内容（限制最大 10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        file_size = log_file.stat().st_size

        if file_size > max_size:
            # 大文件只读取最后 10MB
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                f.seek(file_size - max_size)
                # 跳过第一行（可能不完整）
                f.readline()
                content = f.read()
        else:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

        return success_response(
            data={
                "filename": log_file.name,
                "content": content,
                "size": len(content),
            },
            message="获取成功"
        )

    except Exception as e:
        logger.exception(f"下载日志失败: {e}")
        return error_response(code=500, message=f"下载日志失败: {str(e)}")
