"""日志配置：控制台 + 滚动落盘.

容器里的日志只在 `docker compose logs` 里，翻历史很麻烦，所以额外写一份到
挂载出来的目录，出问题时直接 grep 文件。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import settings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
# 认领自己挂的 handler，重复调用时先拆掉旧的，避免每行日志写好几遍
_MARK = "_wechat_oap_handler"


def setup_logging(
    log_dir: str | None = None,
    level: str | None = None,
    max_mb: int | None = None,
    backups: int | None = None,
) -> None:
    """配置控制台 + 滚动文件日志.

    max_mb 是**总**磁盘预算，由当前文件和 backups 个备份平分——不是每个文件
    各占这么大。默认 50MB / 5 个文件 = 每个 10MB。
    """
    log_dir = log_dir if log_dir is not None else settings.log_dir
    level = (level or settings.log_level).upper()
    max_mb = max_mb if max_mb is not None else settings.log_max_mb
    backups = backups if backups is not None else settings.log_backups

    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT, _DATEFMT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    setattr(console, _MARK, True)
    root.addHandler(console)

    if log_dir:
        # 挂载目录的属主经常和容器用户对不上。落盘失败只是少记日志，绝不能
        # 让服务起不来——降级成只打控制台，并把原因喊出来。
        try:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                directory / "app.log",
                maxBytes=max_mb * 1024 * 1024 // (backups + 1),
                backupCount=backups,
                encoding="utf-8",
            )
        except OSError as exc:
            root.warning(
                "日志目录 %s 不可写(%s)，本次只输出到控制台。"
                "容器内用户是 uid 10001，宿主机执行 chown -R 10001:10001 %s 可修复",
                log_dir, exc, log_dir,
            )
        else:
            file_handler.setFormatter(formatter)
            setattr(file_handler, _MARK, True)
            root.addHandler(file_handler)

    # uvicorn 自带 handler 且默认不向上传播，不改这两行访问日志就进不了文件
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
