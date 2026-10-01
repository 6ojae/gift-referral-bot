import aiosqlite
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "data/bot.db"))

async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                first_name TEXT,
                username TEXT,
                joined_at TEXT NOT NULL,
                total_invites INTEGER DEFAULT 0,
                total_rewards INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invite_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                invite_link TEXT NOT NULL,
                invite_hash TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER NOT NULL,
                invited_id INTEGER NOT NULL UNIQUE,
                invite_link_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                reward_number INTEGER NOT NULL,
                gift_code TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT "pending",
                confirmed_at TEXT
            )
        """)
        await db.commit()

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return await cursor.fetchone()

async def create_user(telegram_id: int, first_name: str, username: str | None, joined_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (telegram_id, first_name, username, joined_at) VALUES (?, ?, ?, ?)", (telegram_id, first_name, username, joined_at))
        await db.commit()

async def update_user_invites(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_invites = total_invites + 1 WHERE telegram_id = ?", (telegram_id,))
        await db.commit()

async def update_user_rewards(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET total_rewards = total_rewards + 1 WHERE telegram_id = ?", (telegram_id,))
        await db.commit()

async def save_invite_link(owner_id: int, invite_link: str, invite_hash: str, created_at: str, expires_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO invite_links (owner_id, invite_link, invite_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)", (owner_id, invite_link, invite_hash, created_at, expires_at))
        await db.commit()
        return cursor.lastrowid

async def get_active_invite(owner_id: int, now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM invite_links WHERE owner_id = ? AND active = 1 AND expires_at > ? ORDER BY id DESC LIMIT 1", (owner_id, now))
        return await cursor.fetchone()

async def get_invite_by_link(invite_link: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM invite_links WHERE invite_link = ? LIMIT 1", (invite_link,))
        return await cursor.fetchone()

async def add_referral(inviter_id: int, invited_id: int, invite_link_id: int, joined_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cursor = await db.execute("INSERT INTO referrals (inviter_id, invited_id, invite_link_id, joined_at) VALUES (?, ?, ?, ?)", (inviter_id, invited_id, invite_link_id, joined_at))
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None

async def get_invite_count(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

import secrets
import string

def generate_gift_code(length: int = 10):
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

async def create_reward(telegram_id: int, reward_number: int, created_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        code = generate_gift_code()
        cursor = await db.execute("INSERT INTO rewards (user_id, reward_number, gift_code, created_at) VALUES (?, ?, ?, ?)", (telegram_id, reward_number, code, created_at))
        await db.execute("UPDATE users SET total_rewards = total_rewards + 1 WHERE telegram_id = ?", (telegram_id,))
        await db.commit()
        return code, cursor.lastrowid

async def get_reward_by_code(gift_code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT r.*, u.telegram_id, u.first_name, u.username, u.joined_at, u.total_invites, u.total_rewards FROM rewards r JOIN users u ON u.telegram_id = r.user_id WHERE r.gift_code = ? LIMIT 1", (gift_code,))
        return await cursor.fetchone()

async def confirm_reward(gift_code: str, confirmed_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("UPDATE rewards SET status = 'confirmed', confirmed_at = ? WHERE gift_code = ? AND status = 'pending'", (confirmed_at, gift_code))
        await db.commit()
        return cursor.rowcount > 0

async def get_user_stats(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
        return await cursor.fetchone()

async def deactivate_expired_invites(now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("UPDATE invite_links SET active = 0 WHERE active = 1 AND expires_at <= ?", (now,))
        await db.commit()
        return cursor.rowcount

async def get_global_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        result = {}
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        result["users"] = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM invite_links WHERE active = 1 AND expires_at > datetime('now')")
        result["active_links"] = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM invite_links")
        result["total_links"] = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM referrals")
        result["invited_users"] = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM rewards WHERE status = 'confirmed'")
        result["confirmed_rewards"] = (await cursor.fetchone())[0]
        return result

async def get_expired_invites(now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM invite_links WHERE active = 1 AND expires_at <= ?", (now,))
        return await cursor.fetchall()
