"""Persistent daily conversations, isolated by unguessable browser identity.

Only explicitly saved memories are long lived. No cross-user retrieval.
Each operation opens its own connection for ThreadingHTTPServer safety.
"""
from __future__ import annotations

import secrets
import json
import sqlite3
import hashlib
import hmac
import re
import time
from contextlib import contextmanager
from pathlib import Path


class DailyStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS identities (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS daily_messages (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS daily_messages_owner ON daily_messages(owner,id);
                CREATE TABLE IF NOT EXISTS daily_memories (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, content TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS daily_memories_owner ON daily_memories(owner,id);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(daily_messages)')}
            if 'evidence' not in columns:
                db.execute("ALTER TABLE daily_messages ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'")
            if 'theme_id' not in columns:
                db.execute('ALTER TABLE daily_messages ADD COLUMN theme_id INTEGER')
            db.execute('''CREATE TABLE IF NOT EXISTS daily_themes (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                goal TEXT NOT NULL DEFAULT '', options TEXT NOT NULL DEFAULT '',
                open_questions TEXT NOT NULL DEFAULT '', decisions TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS daily_themes_owner ON daily_themes(owner,id)')
            identity_columns = {row['name'] for row in db.execute('PRAGMA table_info(identities)')}
            if 'active_theme' not in identity_columns:
                db.execute('ALTER TABLE identities ADD COLUMN active_theme INTEGER')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS daily_accounts (
                    username TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE,
                    password_salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS daily_sessions (
                    token_hash BLOB PRIMARY KEY, owner TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS daily_sessions_owner ON daily_sessions(owner);
                CREATE TABLE IF NOT EXISTS daily_auth_attempts (
                    key TEXT NOT NULL, attempted_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS daily_auth_attempts_key ON daily_auth_attempts(key,attempted_at);
                CREATE TABLE IF NOT EXISTS daily_memory_proposals (
                    id INTEGER PRIMARY KEY, owner TEXT NOT NULL, content TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','saved','dismissed')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS daily_memory_proposals_owner
                    ON daily_memory_proposals(owner,id);
            ''')
            account_columns = {row['name'] for row in db.execute('PRAGMA table_info(daily_accounts)')}
            if 'recovery_hash' not in account_columns:
                db.execute('ALTER TABLE daily_accounts ADD COLUMN recovery_hash BLOB')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_identity(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO identities(id) VALUES (?)', (token,))
        return token

    def known_identity(self, token: str) -> bool:
        if not isinstance(token, str) or len(token) != 43:
            return False
        with self.connect() as db:
            return db.execute('SELECT 1 FROM identities WHERE id=?', (token,)).fetchone() is not None

    def _require(self, owner: str):
        if not self.known_identity(owner):
            raise ValueError('利用者セッションが無効です。画面を再読み込みしてください。')

    def history(self, owner: str, limit: int = 40, *, include_sources: bool = False) -> list[dict]:
        self._require(owner)
        with self.connect() as db:
            rows = db.execute('SELECT role,content,evidence FROM daily_messages WHERE owner=? ORDER BY id DESC LIMIT ?',
                              (owner, max(1, min(limit, 200)))).fetchall()
        result = []
        for row in reversed(rows):
            message = {'role':row['role'], 'content':row['content']}
            if include_sources:
                message.update(json.loads(row['evidence']))
            result.append(message)
        return result

    def append_turn(self, owner: str, user: str, assistant: str, evidence: dict | None = None):
        self._require(owner)
        with self.connect() as db:
            active = db.execute('SELECT active_theme FROM identities WHERE id=?', (owner,)).fetchone()[0]
            db.executemany('INSERT INTO daily_messages(owner,role,content,evidence,theme_id) VALUES (?,?,?,?,?)',
                           [(owner, 'user', user, '{}', active),
                            (owner, 'assistant', assistant, json.dumps(evidence or {}, ensure_ascii=False), active)])
            db.execute('DELETE FROM daily_messages WHERE owner=? AND id NOT IN '
                       '(SELECT id FROM daily_messages WHERE owner=? ORDER BY id DESC LIMIT 200)', (owner, owner))

    def theme_history(self, owner: str, theme_id: int, limit: int = 40) -> list[dict]:
        self._require(owner)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM daily_themes WHERE owner=? AND id=?',
                              (owner, theme_id)).fetchone():
                raise ValueError('テーマが見つかりません。')
            rows = db.execute('SELECT role,content FROM daily_messages WHERE owner=? AND theme_id=? '
                              'ORDER BY id DESC LIMIT ?', (owner, theme_id, max(1, min(limit, 100)))).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_history(self, owner: str):
        self._require(owner)
        with self.connect() as db:
            db.execute('DELETE FROM daily_messages WHERE owner=?', (owner,))

    def memories(self, owner: str) -> list[dict]:
        self._require(owner)
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,content,updated_at FROM daily_memories WHERE owner=? ORDER BY id', (owner,))]

    def save_memory(self, owner: str, content: str, memory_id: int | None = None) -> int:
        self._require(owner)
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 2000:
            raise ValueError('記憶は1〜2000文字で入力してください。')
        with self.connect() as db:
            if memory_id is None:
                if db.execute('SELECT count(*) FROM daily_memories WHERE owner=?', (owner,)).fetchone()[0] >= 100:
                    raise ValueError('記憶は100件までです。不要な記憶を整理してください。')
                return int(db.execute('INSERT INTO daily_memories(owner,content) VALUES (?,?)',
                                      (owner, content.strip())).lastrowid)
            result = db.execute('UPDATE daily_memories SET content=?,updated_at=CURRENT_TIMESTAMP WHERE owner=? AND id=?',
                                (content.strip(), owner, memory_id))
            if result.rowcount != 1:
                raise ValueError('記憶が見つかりません。')
            return memory_id

    def delete_memory(self, owner: str, memory_id: int):
        self._require(owner)
        with self.connect() as db:
            result = db.execute('DELETE FROM daily_memories WHERE owner=? AND id=?', (owner, memory_id))
            if result.rowcount != 1:
                raise ValueError('記憶が見つかりません。')

    def pending_memory_proposal(self, owner: str) -> dict | None:
        self._require(owner)
        with self.connect() as db:
            row = db.execute('SELECT id,content FROM daily_memory_proposals '
                             "WHERE owner=? AND state='pending' ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
        return dict(row) if row else None

    def propose_memory(self, owner: str, content: str) -> dict | None:
        self._require(owner)
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 120:
            return None
        content = content.strip()
        with self.connect() as db:
            pending = db.execute('SELECT id,content FROM daily_memory_proposals '
                                 "WHERE owner=? AND state='pending' ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
            if pending:
                return None
            if db.execute('SELECT 1 FROM daily_memories WHERE owner=? AND content=?', (owner, content)).fetchone():
                return None
            if db.execute('SELECT 1 FROM daily_memory_proposals WHERE owner=? AND content=?',
                          (owner, content)).fetchone():
                return None
            proposal_id = db.execute('INSERT INTO daily_memory_proposals(owner,content,state) VALUES (?,?,?)',
                                     (owner, content, 'pending')).lastrowid
            return {'id':proposal_id, 'content':content}

    def resolve_memory_proposal(self, owner: str, proposal_id: int, action: str,
                                content: str | None = None) -> bool:
        self._require(owner)
        if type(proposal_id) is not int or proposal_id < 1 or action not in ('save', 'dismiss'):
            raise ValueError('記憶提案の操作が不正です。')
        with self.connect() as db:
            row = db.execute('SELECT content FROM daily_memory_proposals '
                             "WHERE owner=? AND id=? AND state='pending'", (owner, proposal_id)).fetchone()
            if not row:
                raise ValueError('記憶提案が見つかりません。')
            if action == 'save':
                value = row['content'] if content is None else content
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
                    raise ValueError('記憶は1〜2000文字で入力してください。')
                if db.execute('SELECT count(*) FROM daily_memories WHERE owner=?', (owner,)).fetchone()[0] >= 100:
                    raise ValueError('記憶は100件までです。不要な記憶を整理してください。')
                db.execute('INSERT INTO daily_memories(owner,content) VALUES (?,?)', (owner, value.strip()))
            db.execute('UPDATE daily_memory_proposals SET state=? WHERE owner=? AND id=?',
                       ('saved' if action == 'save' else 'dismissed', owner, proposal_id))
        return action == 'save'

    def themes(self, owner: str) -> dict:
        self._require(owner)
        with self.connect() as db:
            items = [dict(row) for row in db.execute(
                'SELECT id,title,goal,options,open_questions,decisions,updated_at '
                'FROM daily_themes WHERE owner=? ORDER BY updated_at DESC,id DESC', (owner,))]
            active = db.execute('SELECT active_theme FROM identities WHERE id=?', (owner,)).fetchone()[0]
        return {'themes': items, 'activeThemeId': active}

    def active_theme(self, owner: str) -> dict | None:
        self._require(owner)
        with self.connect() as db:
            row = db.execute('SELECT t.title,t.goal,t.options,t.open_questions,t.decisions '
                             'FROM daily_themes t JOIN identities i ON i.active_theme=t.id '
                             'WHERE i.id=? AND t.owner=?', (owner, owner)).fetchone()
        return dict(row) if row else None

    def save_theme(self, owner: str, fields: dict, theme_id: int | None = None) -> int:
        self._require(owner)
        if not isinstance(fields, dict):
            raise ValueError('テーマの内容が不正です。')
        keys = ('title', 'goal', 'options', 'open_questions', 'decisions')
        values = []
        for key in keys:
            value = fields.get(key, '')
            if not isinstance(value, str) or len(value.strip()) > (120 if key == 'title' else 2000):
                raise ValueError('テーマの内容が長すぎるか不正です。')
            values.append(value.strip())
        if not values[0]:
            raise ValueError('テーマ名を入力してください。')
        with self.connect() as db:
            if theme_id is None:
                if db.execute('SELECT count(*) FROM daily_themes WHERE owner=?', (owner,)).fetchone()[0] >= 50:
                    raise ValueError('テーマは50件までです。')
                theme_id = int(db.execute(
                    'INSERT INTO daily_themes(owner,title,goal,options,open_questions,decisions) '
                    'VALUES (?,?,?,?,?,?)', (owner, *values)).lastrowid)
                db.execute('UPDATE identities SET active_theme=? WHERE id=?', (theme_id, owner))
            else:
                result = db.execute(
                    'UPDATE daily_themes SET title=?,goal=?,options=?,open_questions=?,decisions=?, '
                    'updated_at=CURRENT_TIMESTAMP WHERE owner=? AND id=?', (*values, owner, theme_id))
                if result.rowcount != 1:
                    raise ValueError('テーマが見つかりません。')
        return theme_id

    def select_theme(self, owner: str, theme_id: int | None):
        self._require(owner)
        with self.connect() as db:
            if theme_id is not None and not db.execute(
                    'SELECT 1 FROM daily_themes WHERE owner=? AND id=?', (owner, theme_id)).fetchone():
                raise ValueError('テーマが見つかりません。')
            db.execute('UPDATE identities SET active_theme=? WHERE id=?', (theme_id, owner))

    def delete_theme(self, owner: str, theme_id: int):
        self._require(owner)
        with self.connect() as db:
            result = db.execute('DELETE FROM daily_themes WHERE owner=? AND id=?', (owner, theme_id))
            if result.rowcount != 1:
                raise ValueError('テーマが見つかりません。')
            db.execute('UPDATE identities SET active_theme=NULL WHERE id=? AND active_theme=?', (owner, theme_id))

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2**14, r=8, p=5,
                              maxmem=64 * 1024 * 1024, dklen=32)

    @staticmethod
    def _validate_credentials(username: str, password: str):
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{3,32}', username):
            raise ValueError('ユーザー名は半角英数字・_・-の3〜32文字で入力してください。')
        if not isinstance(password, str) or not 12 <= len(password) <= 128 or len(password.encode('utf-8')) > 512:
            raise ValueError('パスワードは12〜128文字で入力してください。')

    def local_counts(self, owner: str) -> dict:
        self._require(owner)
        with self.connect() as db:
            return {name: db.execute(f'SELECT count(*) FROM {table} WHERE owner=?', (owner,)).fetchone()[0]
                    for name, table in (('messages', 'daily_messages'), ('memories', 'daily_memories'),
                                        ('themes', 'daily_themes'))}

    def account_name(self, owner: str) -> str | None:
        with self.connect() as db:
            row = db.execute('SELECT username FROM daily_accounts WHERE owner=?', (owner,)).fetchone()
        return row[0] if row else None

    def register_account(self, anonymous_owner: str, username: str, password: str,
                         *, migrate_local: bool = False) -> tuple[str, str]:
        self._validate_credentials(username, password)
        self._require(anonymous_owner)
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)
        owner = secrets.token_urlsafe(32)
        recovery_code = secrets.token_urlsafe(32)
        recovery_hash = hashlib.sha256(recovery_code.encode('ascii')).digest()
        with self.connect() as db:
            if db.execute('SELECT 1 FROM daily_accounts WHERE owner=?', (anonymous_owner,)).fetchone():
                raise ValueError('すでにアカウントに登録済みです。')
            counts = [db.execute(f'SELECT count(*) FROM {table} WHERE owner=?', (anonymous_owner,)).fetchone()[0]
                      for table in ('daily_messages', 'daily_memories', 'daily_themes')]
            if any(counts) and not migrate_local:
                raise ValueError('このブラウザの履歴・記憶・テーマの移行を確認してください。')
            if db.execute('SELECT 1 FROM daily_accounts WHERE username=?', (username.casefold(),)).fetchone():
                raise ValueError('そのユーザー名は利用できません。')
            db.execute('INSERT INTO identities(id,active_theme) SELECT ?,active_theme FROM identities WHERE id=?',
                       (owner, anonymous_owner))
            db.execute('INSERT INTO daily_accounts(username,owner,password_salt,password_hash,recovery_hash) '
                       'VALUES (?,?,?,?,?)', (username.casefold(), owner, salt, password_hash, recovery_hash))
            for table in ('daily_messages', 'daily_memories', 'daily_themes'):
                db.execute(f'UPDATE {table} SET owner=? WHERE owner=?', (owner, anonymous_owner))
            db.execute('UPDATE daily_memory_proposals SET owner=? WHERE owner=?', (owner, anonymous_owner))
            # Keep the emptied browser identity valid for requests already in flight.
            db.execute('UPDATE identities SET active_theme=NULL WHERE id=?', (anonymous_owner,))
        return owner, recovery_code

    def authenticate_account(self, username: str, password: str) -> str:
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 32 or len(password) > 128:
            raise ValueError('ユーザー名またはパスワードが違います。')
        with self.connect() as db:
            row = db.execute('SELECT owner,password_salt,password_hash FROM daily_accounts WHERE username=?',
                             (username.casefold(),)).fetchone()
        salt = row['password_salt'] if row else b'\0' * 16
        expected = row['password_hash'] if row else b'\0' * 32
        result = self._password_hash(password, salt)
        if not row or not hmac.compare_digest(result, expected):
            raise ValueError('ユーザー名またはパスワードが違います。')
        return row['owner']

    def recover_account(self, username: str, recovery_code: str, new_password: str) -> tuple[str, str]:
        self._validate_credentials(username, new_password)
        if not isinstance(recovery_code, str) or len(recovery_code) != 43:
            raise ValueError('ユーザー名または復旧コードが違います。')
        with self.connect() as db:
            row = db.execute('SELECT owner,recovery_hash FROM daily_accounts WHERE username=?',
                             (username.casefold(),)).fetchone()
        supplied = hashlib.sha256(recovery_code.encode('utf-8')).digest()
        expected = row['recovery_hash'] if row and row['recovery_hash'] else b'\0' * 32
        if not row or not hmac.compare_digest(supplied, expected):
            raise ValueError('ユーザー名または復旧コードが違います。')
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(new_password, salt)
        new_code = secrets.token_urlsafe(32)
        new_hash = hashlib.sha256(new_code.encode('ascii')).digest()
        with self.connect() as db:
            result = db.execute('UPDATE daily_accounts SET password_salt=?,password_hash=?,recovery_hash=? '
                                'WHERE owner=? AND recovery_hash=?',
                                (salt, password_hash, new_hash, row['owner'], expected))
            if result.rowcount != 1:
                raise ValueError('復旧コードはすでに使用されています。')
            db.execute('DELETE FROM daily_sessions WHERE owner=?', (row['owner'],))
        return row['owner'], new_code

    def reissue_recovery_code(self, owner: str, password: str) -> str:
        username = self.account_name(owner)
        if not username or self.authenticate_account(username, password) != owner:
            raise ValueError('パスワードが違います。')
        new_code = secrets.token_urlsafe(32)
        digest = hashlib.sha256(new_code.encode('ascii')).digest()
        with self.connect() as db:
            db.execute('UPDATE daily_accounts SET recovery_hash=? WHERE owner=?', (digest, owner))
        return new_code

    def new_session(self, owner: str) -> str:
        if not self.account_name(owner):
            raise ValueError('アカウントが見つかりません。')
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode('ascii')).digest()
        with self.connect() as db:
            db.execute('DELETE FROM daily_sessions WHERE expires_at<?', (int(time.time()),))
            db.execute('INSERT INTO daily_sessions(token_hash,owner,expires_at) VALUES (?,?,?)',
                       (digest, owner, int(time.time()) + 30 * 86400))
        return token

    def session_owner(self, token: str) -> str | None:
        if not isinstance(token, str) or len(token) != 43:
            return None
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        with self.connect() as db:
            row = db.execute('SELECT owner FROM daily_sessions WHERE token_hash=? AND expires_at>?',
                             (digest, int(time.time()))).fetchone()
        return row[0] if row else None

    def end_session(self, token: str):
        if not isinstance(token, str) or len(token) != 43:
            return
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        with self.connect() as db:
            db.execute('DELETE FROM daily_sessions WHERE token_hash=?', (digest,))

    def allow_auth_attempt(self, key: str, limit: int = 5, seconds: int = 600) -> bool:
        now = int(time.time())
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        with self.connect() as db:
            db.execute('DELETE FROM daily_auth_attempts WHERE attempted_at<?', (now-seconds,))
            if db.execute('SELECT count(*) FROM daily_auth_attempts WHERE key=?', (digest,)).fetchone()[0] >= limit:
                return False
            db.execute('INSERT INTO daily_auth_attempts(key,attempted_at) VALUES (?,?)', (digest, now))
        return True

    def migrate_local(self, anonymous_owner: str, account_owner: str) -> dict:
        if anonymous_owner == account_owner or not self.account_name(account_owner):
            raise ValueError('移行先が不正です。')
        self._require(anonymous_owner)
        with self.connect() as db:
            if db.execute('SELECT 1 FROM daily_accounts WHERE owner=?', (anonymous_owner,)).fetchone():
                raise ValueError('登録済みアカウントのデータは移行できません。')
            counts = {}
            for name, table, maximum in (('messages','daily_messages',200),
                                         ('memories','daily_memories',100),
                                         ('themes','daily_themes',50)):
                source = db.execute(f'SELECT count(*) FROM {table} WHERE owner=?', (anonymous_owner,)).fetchone()[0]
                target = db.execute(f'SELECT count(*) FROM {table} WHERE owner=?', (account_owner,)).fetchone()[0]
                if source + target > maximum:
                    raise ValueError(f'{name}の件数が上限を超えます。移行前に整理してください。')
                counts[name] = source
            old_active = db.execute('SELECT active_theme FROM identities WHERE id=?', (anonymous_owner,)).fetchone()[0]
            for table in ('daily_messages', 'daily_memories', 'daily_themes'):
                db.execute(f'UPDATE {table} SET owner=? WHERE owner=?', (account_owner, anonymous_owner))
            db.execute('UPDATE daily_memory_proposals SET owner=? WHERE owner=?', (account_owner, anonymous_owner))
            db.execute('UPDATE identities SET active_theme=COALESCE(active_theme,?) WHERE id=?',
                       (old_active, account_owner))
            db.execute('UPDATE identities SET active_theme=NULL WHERE id=?', (anonymous_owner,))
        return counts
