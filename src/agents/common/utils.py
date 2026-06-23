import os
import logging


def setup_logger(name, log_file, filemode="w", level=logging.INFO):
    """Function to dynamically set up as many loggers as you want."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    handler = logging.FileHandler(log_file, mode=filemode)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger
