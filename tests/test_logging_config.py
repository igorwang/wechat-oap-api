"""日志落盘配置."""

import logging
import os
from logging.handlers import RotatingFileHandler

import pytest

from app.logging_config import setup_logging


def _teardown(names=("wechat-oap",)):
    for name in names:
        logging.getLogger(name).handlers.clear()


def test_writes_records_to_a_rotating_file(tmp_path):
    log_dir = tmp_path / "log"
    setup_logging(log_dir=str(log_dir), level="INFO")

    logging.getLogger("app.test").info("hello 日志")

    logfile = log_dir / "app.log"
    assert logfile.exists()
    content = logfile.read_text(encoding="utf-8")
    assert "hello 日志" in content
    assert "app.test" in content


def test_creates_the_directory_if_missing(tmp_path):
    log_dir = tmp_path / "deep" / "nested" / "log"
    setup_logging(log_dir=str(log_dir), level="INFO")
    assert log_dir.is_dir()


def test_empty_log_dir_disables_file_output(tmp_path, capsys):
    """未配置目录时只往控制台打，不该因为没有目录就炸掉."""
    setup_logging(log_dir="", level="INFO")
    logging.getLogger("app.test").info("console only")
    assert not list(tmp_path.iterdir())


def test_repeated_setup_does_not_duplicate_handlers(tmp_path):
    """lifespan 里可能被调用多次；重复挂 handler 会让每行日志写好几遍."""
    log_dir = tmp_path / "log"
    setup_logging(log_dir=str(log_dir), level="INFO")
    setup_logging(log_dir=str(log_dir), level="INFO")

    logging.getLogger("app.test").info("only once")

    content = (log_dir / "app.log").read_text(encoding="utf-8")
    assert content.count("only once") == 1


def test_debug_is_filtered_at_info_level(tmp_path):
    log_dir = tmp_path / "log"
    setup_logging(log_dir=str(log_dir), level="INFO")

    logging.getLogger("app.test").debug("noisy detail")
    logging.getLogger("app.test").warning("worth keeping")

    content = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "noisy detail" not in content
    assert "worth keeping" in content


def test_total_size_stays_under_the_cap(tmp_path):
    """轮转要真的封顶：总量算上备份也不能超过 max_mb."""
    log_dir = tmp_path / "log"
    setup_logging(log_dir=str(log_dir), level="INFO", max_mb=1, backups=2)

    logger = logging.getLogger("app.test")
    line = "x" * 900
    for _ in range(3000):          # 约 2.7MB 原始输出，远超 1MB 上限
        logger.info(line)

    files = sorted(log_dir.glob("app.log*"))
    total = sum(f.stat().st_size for f in files)
    assert len(files) <= 3, f"应最多 1 个当前 + 2 个备份，实际 {[f.name for f in files]}"
    # 单个文件在写完当前行后才轮转，允许一行的溢出
    assert total <= 1 * 1024 * 1024 + 4096, f"总量 {total} 超过 1MB 上限"


def test_rotation_settings_split_the_budget_across_files(tmp_path):
    """max_mb 是总预算，按 backups+1 个文件平分，而不是每个文件都这么大."""
    from logging.handlers import RotatingFileHandler

    setup_logging(log_dir=str(tmp_path / "log"), level="INFO", max_mb=50, backups=4)
    handler = next(
        h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
    )
    assert handler.backupCount == 4
    assert handler.maxBytes * (handler.backupCount + 1) == 50 * 1024 * 1024


@pytest.mark.skipif(os.geteuid() == 0, reason="root 绕过文件权限，测不出来")
def test_unwritable_dir_falls_back_to_console_instead_of_crashing(tmp_path, caplog):
    """日志目录没权限时只能少记日志，绝不能让服务起不来."""
    log_dir = tmp_path / "readonly"
    log_dir.mkdir()
    log_dir.chmod(0o500)
    try:
        setup_logging(log_dir=str(log_dir), level="INFO")   # 不抛
        logging.getLogger("app.test").info("still alive")
        handlers = logging.getLogger().handlers
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)
        assert not any(isinstance(h, RotatingFileHandler) for h in handlers)
    finally:
        log_dir.chmod(0o700)
