-- server/schema.sql

PRAGMA encoding = 'UTF-8';
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA busy_timeout = 5000;

BEGIN;

-- accounts
CREATE TABLE IF NOT EXISTS accounts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  email        TEXT NOT NULL COLLATE NOCASE UNIQUE,
  group_id     TEXT NOT NULL,
  password     TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT '未登录' CHECK (status IN ('未登录','登录成功','登录失败')),
  username     TEXT,
  birthday     TEXT,
  version      INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
  updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
  is_delete    INTEGER NOT NULL DEFAULT 0

);
CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
CREATE INDEX IF NOT EXISTS idx_accounts_group_id ON accounts(group_id);
CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);

-- 创建用户表
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    password    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);

-- 创建项目表
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);

-- 创建项目-账户关联表（使用记录）
CREATE TABLE IF NOT EXISTS project_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    account_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),

    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (user_id) REFERENCES users(id),

    -- 确保同一个账号不会重复分配给同一个项目
    UNIQUE(project_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_project_assignments_project ON project_assignments(project_id);
CREATE INDEX IF NOT EXISTS idx_project_assignments_account ON project_assignments(account_id);
CREATE INDEX IF NOT EXISTS idx_project_assignments_user ON project_assignments(user_id);


--辅助邮箱
CREATE TABLE IF NOT EXISTS account_recovery_email (
  group_id   TEXT NOT NULL,
  email      TEXT NOT NULL,
  PRIMARY KEY (group_id, email)
);
CREATE INDEX IF NOT EXISTS idx_recovery_email_email ON account_recovery_email(email);
--辅助电话

CREATE TABLE IF NOT EXISTS account_recovery_phone (
  group_id     TEXT NOT NULL,
  phone        TEXT NOT NULL,
  PRIMARY KEY (group_id, phone)
);
CREATE INDEX IF NOT EXISTS idx_recovery_phone_phone ON account_recovery_phone(phone);

--msal token表
CREATE TABLE IF NOT EXISTS account_token (
    group_id      TEXT PRIMARY KEY,
    access_token  TEXT NOT NULL,    -- 用于 API 请求 (有效期通常 60-90 分钟)
    refresh_token TEXT NOT NULL,    -- 用于换取新 AT (有效期 90天-永久)
    id_token      TEXT,             -- OIDC 身份令牌 (包含用户信息，可选)
    at_expires_at INTEGER NOT NULL, -- access_token过期时间(3600s)
    rt_expires_at INTEGER NOT NULL, -- refresh_token过期时间(90days)
    scope         TEXT,             -- 记录授权范围 (e.g. "Mail.Read User.Read")
    tenant_id     TEXT,             -- 微软的 Tenant ID (多租户应用必存)
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
    updated_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);
CREATE INDEX IF NOT EXISTS idx_account_token_group ON account_token(group_id);

CREATE TABLE IF NOT EXISTS account_version (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id             TEXT NOT NULL,
  version              INTEGER NOT NULL,
  emails_snapshot_json TEXT NOT NULL,
  password             TEXT NOT NULL,
  status               TEXT NOT NULL,
  username             TEXT,
  birthday             TEXT,
  recovery_emails_json TEXT NOT NULL,
  recovery_phones_json TEXT NOT NULL,
  note                 TEXT,
  created_by           TEXT,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
  UNIQUE(group_id, version)
);
CREATE INDEX IF NOT EXISTS idx_accver_accid_ver ON account_version(group_id, version DESC);

-- mails
CREATE TABLE IF NOT EXISTS mail_message (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id           TEXT NOT NULL,
  msg_uid            TEXT,
  msg_id             TEXT,
  subject            TEXT NOT NULL DEFAULT '',
  subject_lc         TEXT GENERATED ALWAYS AS (lower(subject)) STORED,
  from_addr          TEXT NOT NULL DEFAULT '',
  from_addr_lc       TEXT GENERATED ALWAYS AS (lower(from_addr)) STORED,
  from_name          TEXT,
  from_name_lc       TEXT GENERATED ALWAYS AS (lower(coalesce(from_name, ''))) STORED,

  to_joined          TEXT NOT NULL DEFAULT '',
  to_joined_lc       TEXT GENERATED ALWAYS AS (lower(to_joined)) STORED,

  folder_id          TEXT,                      -- Graph API文件夹ID
  labels_joined      TEXT NOT NULL DEFAULT '',
  labels_joined_lc   TEXT GENERATED ALWAYS AS (lower(labels_joined)) STORED,

  sent_at            TEXT,
  received_at        TEXT,
  size_bytes         INTEGER,
  has_attachments  INTEGER NOT NULL DEFAULT 0,
  flags              TEXT NOT NULL DEFAULT 'UNREAD',
  snippet            TEXT,

  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),

  UNIQUE(group_id, msg_uid)
);

CREATE INDEX IF NOT EXISTS idx_mail_acc_recv
  ON mail_message(group_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mail_acc_from
  ON mail_message(group_id, from_addr_lc, id);
CREATE INDEX IF NOT EXISTS idx_mail_acc_from_name
  ON mail_message(group_id, from_name_lc, id);
CREATE INDEX IF NOT EXISTS idx_mail_acc_subject
  ON mail_message(group_id, subject_lc, id);
CREATE INDEX IF NOT EXISTS idx_mail_acc_to_lc
  ON mail_message(group_id, to_joined_lc, id);
CREATE INDEX IF NOT EXISTS idx_mail_acc_folder
  ON mail_message(group_id, folder_id, received_at DESC);
--收件人
CREATE TABLE IF NOT EXISTS mail_recipient (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id   INTEGER NOT NULL REFERENCES mail_message(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL DEFAULT 'to' CHECK (kind IN ('to','cc','bcc')),
  display_name TEXT,
  addr         TEXT NOT NULL,
  addr_lc      TEXT GENERATED ALWAYS AS (lower(addr)) STORED,
  UNIQUE(message_id, addr_lc)
);


CREATE INDEX IF NOT EXISTS idx_rec_acc_addr ON mail_recipient(account_id, addr_lc, message_id);
CREATE INDEX IF NOT EXISTS idx_rec_msg ON mail_recipient(message_id);

--邮箱内容
CREATE TABLE IF NOT EXISTS mail_body (
  message_id   INTEGER PRIMARY KEY REFERENCES mail_message(id) ON DELETE CASCADE,
  headers      TEXT,
  body_plain   TEXT,
  body_html    TEXT
);
--邮箱附件
CREATE TABLE IF NOT EXISTS mail_attachment (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id     INTEGER NOT NULL REFERENCES mail_message(id) ON DELETE CASCADE,
  attachment_id  TEXT NOT NULL,
  filename TEXT,           -- 显示的文件名 (如 "invoice.pdf")
  content_type TEXT,       -- MIME 类型 (如 "application/pdf", "image/png")
  size INTEGER DEFAULT 0,  -- 文件大小 (字节)，用于前端显示和磁盘空间预判
-- 如果是正文截图，is_inline=1，且 content_id 会有值 (如 "cid:image001")
-- 渲染邮件 HTML 时，需要用本地路径替换 src="cid:..."
  is_inline BOOLEAN DEFAULT 0,
  content_id TEXT,
-- 6. 存储与状态
  file_path TEXT,          -- 磁盘上的绝对路径或相对路径 (下载成功后填入)
  download_status TEXT DEFAULT 'PENDING' CHECK (download_status IN ('PENDING','DOWNLOADING','DONE','FAILED')),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);
CREATE INDEX IF NOT EXISTS idx_mail_attachment_msg_id ON mail_attachment(message_id);
CREATE INDEX IF NOT EXISTS idx_mail_attachment_ms_id ON mail_attachment(attachment_id);
--邮箱目录
CREATE TABLE IF NOT EXISTS mail_folders (
    folder_id        TEXT PRIMARY KEY,   -- Graph API 的 folder ID
    group_id         TEXT NOT NULL,      --区分属于哪个账户
    display_name     TEXT NOT NULL,
    well_known_name  TEXT,               -- inbox, sentitems, drafts 等
    parent_folder_id TEXT,
    total_count      INTEGER DEFAULT 0,  -- 文件夹内邮件总数
    unread_count     INTEGER DEFAULT 0,
    delta_link       TEXT,               -- 该文件夹的 Delta Link
    skip_token       TEXT,
    last_sync_at     TEXT,               -- 该文件夹上次同步时间
    last_msg_uid     TEXT,               -- 该文件夹上次同步时间
    synced_count     INTEGER DEFAULT 0,  -- 该文件夹已同步数量
    updated_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);
CREATE INDEX IF NOT EXISTS idx_mail_folders_group ON mail_folders(group_id);

COMMIT;
PRAGMA user_version = 5;
