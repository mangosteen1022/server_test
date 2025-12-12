"""服务器配置"""

import os
from pathlib import Path

# 基础路径
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", BASE_DIR / "static")).resolve()
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "database" / "accounts.db")).resolve()

SCHEMA_SQL = Path(os.environ.get("SCHEMA_PATH", BASE_DIR / "database" / "schema.sql")).resolve()
TOKEN_DIR = Path(os.environ.get("TOKEN_DIR", BASE_DIR / "database" / "token")).resolve()

# CORS配置
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]

# API配置
API_TITLE = "Outlook Mail + Accounts API (SQLite)"
API_VERSION = "2.0.0"

# MSAL/Graph API配置
MSAL_CLIENT_ID = os.environ.get("MSAL_CLIENT_ID", "f4a5101b-9441-48f4-968f-3ef3da7b7290")
MSAL_AUTHORITY = "https://login.microsoftonline.com/common"
MSAL_SCOPES = ["User.Read", "Mail.Read", "Mail.ReadWrite", "Mail.Send"]
MSAL_REDIRECT_PORT = int(os.environ.get("MSAL_REDIRECT_PORT", 53100))
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# 邮件同步配置
DEFAULT_SYNC_DAYS = int(os.environ.get("DEFAULT_SYNC_DAYS", 30))
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", 1000))
SYNC_TIMEOUT = int(os.environ.get("SYNC_TIMEOUT", 300))
LOGIN_POOL_MAX_WORKERS = 50
CHECK_POOL_MAX_WORKERS = 50

# 数据库连接池配置
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", 20))
DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", 5))
DB_TIMEOUT = int(os.environ.get("DB_TIMEOUT", 30))

