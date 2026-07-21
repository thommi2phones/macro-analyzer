"""Telethon Phase-0 smoke test.

Goal: prove we can authenticate the user's Telegram account, list every
chat they're a member of, and read recent messages from any chat —
WITHOUT touching the DB, the extractor, or any other part of the app.
If this works end-to-end, the full deal-flow pipeline plan in
~/.claude/plans/i-think-we-should-curried-bengio.md is greenlit.

Usage:
  # First run — auths the account interactively (phone → SMS → optional 2FA).
  # Session file persisted to data/telegram.session for subsequent runs.
  uv run python scripts/telegram_smoke_test.py list-chats

  # Once you've found the PE Deal Flow group's id in the list:
  uv run python scripts/telegram_smoke_test.py peek <chat_id> --n 20

  # Optional: filter the list to titles containing a substring
  uv run python scripts/telegram_smoke_test.py list-chats --grep "deal"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Path-safe import without needing the package installed
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from macro_positioning.core.settings import settings  # noqa: E402


def _require_credentials() -> None:
    """Bail with a clear error if api_id / api_hash aren't configured."""
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print(
            "ERROR: Telegram credentials missing.\n"
            "Set MPA_TELEGRAM_API_ID and MPA_TELEGRAM_API_HASH in .env.\n"
            "Get them from https://my.telegram.org → API development tools.",
            file=sys.stderr,
        )
        sys.exit(2)


def _make_client():
    """Construct a Telethon client. Imported here so the script loads
    even when telethon isn't installed yet (graceful error)."""
    try:
        from telethon import TelegramClient  # noqa: WPS433
    except ImportError:
        print(
            "ERROR: telethon is not installed.\n"
            "Run: uv add telethon",
            file=sys.stderr,
        )
        sys.exit(2)

    settings.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
    # Telethon appends '.session' itself, so strip if present.
    session_str = str(settings.telegram_session_path).removesuffix(".session")
    return TelegramClient(
        session_str,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )


async def cmd_list_chats(grep: str | None) -> None:
    """Print every dialog the user is a member of."""
    client = _make_client()
    # client.start() will prompt for phone / code / 2FA on first run via stdin.
    await client.start()
    me = await client.get_me()
    print(f"\nauthenticated as: {me.first_name} (id={me.id})\n")

    print(f"{'idx':>3}  {'kind':10s}  {'chat_id':>16s}  {'unread':>6s}  title")
    print("-" * 80)
    g = (grep or "").lower()
    n = 0
    async for dialog in client.iter_dialogs():
        title = dialog.name or "(untitled)"
        if g and g not in title.lower():
            continue
        kind = (
            "channel" if dialog.is_channel
            else "group" if dialog.is_group
            else "dm" if dialog.is_user
            else "other"
        )
        unread = dialog.unread_count or 0
        n += 1
        print(f"{n:>3}  {kind:10s}  {dialog.id:>16d}  {unread:>6d}  {title[:60]}")
    print(f"\n{n} dialog{'s' if n != 1 else ''} shown")
    await client.disconnect()


async def cmd_peek(chat_id: int, n: int, download_dir: Path | None) -> None:
    """Print the last N messages from a chat — sender, ts, reply ref, body.

    When ``download_dir`` is set, also pull every attached photo / document
    into that directory. Telethon downloads the highest-resolution version
    available; for photos that's the full JPEG/PNG, no quality loss vs a
    manual screenshot.
    """
    client = _make_client()
    await client.start()

    try:
        entity = await client.get_entity(chat_id)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR resolving chat_id {chat_id}: {e}", file=sys.stderr)
        await client.disconnect()
        sys.exit(2)
    print(f"\n=== {getattr(entity, 'title', getattr(entity, 'first_name', chat_id))} (id={chat_id}) ===\n")

    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
        print(f"(downloading media to {download_dir})\n")

    # iter_messages returns newest first; reverse for chronological display.
    msgs = []
    async for m in client.iter_messages(entity, limit=n):
        msgs.append(m)
    msgs.reverse()

    media_count = 0
    media_bytes = 0
    for m in msgs:
        sender = await m.get_sender() if m.sender_id else None
        sender_name = (
            (getattr(sender, "first_name", None) or getattr(sender, "username", None) or str(m.sender_id))
            if sender else "?"
        )
        ts = m.date.isoformat() if m.date else "?"
        reply = f" ↪ reply_to={m.reply_to_msg_id}" if m.reply_to_msg_id else ""
        media_tag = ""
        if m.media:
            media_tag = f" [+{type(m.media).__name__}]"
            if download_dir:
                # Telethon picks an appropriate extension automatically.
                path = await m.download_media(file=str(download_dir / f"msg_{m.id}"))
                if path:
                    size = Path(path).stat().st_size
                    media_count += 1
                    media_bytes += size
                    media_tag = f" [↓ {Path(path).name} · {size // 1024}KB]"
        body = (m.message or "").replace("\n", " ⏎ ")
        if len(body) > 500:
            body = body[:497] + "…"
        print(f"[{ts}] {sender_name:20s}{reply}{media_tag}  {body}")

    print(f"\n{len(msgs)} message{'s' if len(msgs) != 1 else ''} shown")
    if download_dir and media_count:
        print(f"{media_count} media file{'s' if media_count != 1 else ''} downloaded ({media_bytes // 1024} KB total)")
    await client.disconnect()


def main() -> int:
    _require_credentials()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-chats", help="List all chats the user is in")
    p_list.add_argument("--grep", default=None,
                        help="Filter to titles containing this substring (case-insensitive)")

    p_peek = sub.add_parser("peek", help="Read the last N messages from one chat")
    p_peek.add_argument("chat_id", type=int, help="Numeric chat id from list-chats")
    p_peek.add_argument("--n", type=int, default=20, help="Number of messages (default 20)")
    p_peek.add_argument("--download", type=Path, default=None,
                        help="If set, download all attached media into this directory")

    args = ap.parse_args()
    if args.cmd == "list-chats":
        asyncio.run(cmd_list_chats(args.grep))
    elif args.cmd == "peek":
        asyncio.run(cmd_peek(args.chat_id, args.n, args.download))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
