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

--msal cache key表
CREATE TABLE IF NOT EXISTS account_token_cache (
  group_id    TEXT NOT NULL,
  uuid        TEXT NOT NULL COLLATE NOCASE CHECK (uuid = lower(uuid)),
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc')),
  PRIMARY KEY (group_id, uuid)
);
CREATE INDEX IF NOT EXISTS idx_token_cache_uuid ON account_token_cache(group_id);

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
  account_id         INTEGER REFERENCES accounts(id) ON DELETE SET NULL,

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
  account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE SET NULL,
  kind         TEXT NOT NULL DEFAULT 'to',
  addr         TEXT NOT NULL,
  addr_lc      TEXT GENERATED ALWAYS AS (lower(addr)) STORED,
  CHECK (kind IN ('to','cc','bcc'))
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
  group_id       TEXT NOT NULL,
  storage_url    TEXT NOT NULL,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);
CREATE INDEX IF NOT EXISTS idx_attach_msg ON mail_attachment(message_id);
CREATE INDEX IF NOT EXISTS idx_attach_acc ON mail_attachment(group_id, id);

--邮箱文件夹
CREATE TABLE IF NOT EXISTS mail_folder (
    id TEXT NOT NULL,                       -- Graph API的文件夹ID
    group_id TEXT NOT NULL,
    display_name TEXT NOT NULL,             -- 显示名称（如"收件箱"、"Inbox"）
    well_known_name TEXT,                   -- 标准名称（inbox, sent, drafts, deleted, junk, archive）
    parent_folder_id TEXT,                  -- 父文件夹ID
    PRIMARY KEY (id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_folder_account ON mail_folder(group_id);
CREATE INDEX IF NOT EXISTS idx_folder_well_known ON mail_folder(group_id, well_known_name);

--邮箱同步状态
CREATE TABLE IF NOT EXISTS mail_sync_state (
    group_id    TEXT PRIMARY KEY,
    last_sync_time TEXT,
    last_msg_uid TEXT,
    delta_link TEXT,  -- Microsoft Graph的deltaLink
    skip_token TEXT,   -- 分页token
    total_synced INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now','utc'))
);

COMMIT;
PRAGMA user_version = 5;
