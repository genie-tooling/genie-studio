from loguru import logger
import sys, pathlib, datetime, os

LOG_PATH = pathlib.Path.home() / ".patchmind"
LOG_PATH.mkdir(exist_ok=True)
log_file = LOG_PATH / f"patchmind_{datetime.datetime.now():%Y%m%d}.log"

logger.remove()
logger.add(sys.stderr, level="DEBUG", enqueue=True, backtrace=True, diagnose=True)
logger.add(str(log_file), rotation="5 MB", retention="10 days", level="DEBUG", enqueue=True, backtrace=True, diagnose=True)

logger.debug("Logger initialised → %s", log_file)
