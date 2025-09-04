import os
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import PeerUser

# ================= CONFIG =================
api_id = int(os.getenv("API_ID", "your_api_id"))
api_hash = os.getenv("API_HASH", "your_api_hash")
session_string = os.getenv("SESSION", "your_session_string")

ADMINS = [123456789]  # <-- apna Telegram ID daalna yaha

save_file = "saved_items.txt"
if not os.path.exists(save_file):
    open(save_file, "w").close()

client = TelegramClient(StringSession(session_string), api_id, api_hash)

# ================= GLOBAL VARS =================
last_reply_time = {}  # track per-user autoreplies
scheduled_tasks = {}  # scheduled DMs
spam_tracker = {}     # spam control

# ================= UTILS =================
def is_admin(user_id):
    return user_id in ADMINS

def is_night():
    now = datetime.now().hour
    return 21 <= now or now < 7  # 9pm - 7am

# ================= SAVE COMMAND =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.save"))
async def save_handler(event):
    reply = await event.get_reply_message()
    if not reply:
        await event.reply("⚠️ Reply to the message you want to save.")
        return
    try:
        chat = await event.get_chat()
        chat_name = getattr(chat, "title", None) or getattr(chat, "username", None) or "Private Chat"
        chat_id = event.chat_id

        if reply.media:
            fwd = await client.send_file("me", reply.media, caption=reply.text or "", as_copy=True)
        else:
            fwd = await client.send_message("me", reply.text or "")

        link_info = f"\n\n🔗 From: {chat_name} (ID: {chat_id})"
        await client.send_message("me", link_info)

        with open(save_file, "a", encoding="utf-8") as f:
            f.write((reply.text or "[Media]") + " | " + str(chat_id) + "\n")

        await event.respond("✅ Saved successfully.")
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")

# ================= LIST COMMAND =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.list"))
async def list_saved(event):
    with open(save_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines:
        await event.respond("📂 No saved items.")
        return

    msg = "📋 Saved Items:\n"
    for i, line in enumerate(lines, 1):
        short = line.strip().split("|")[0]
        if len(short) > 15:
            short = short[:15] + "..."
        msg += f"{i}. {short}\n"
    await event.respond(msg)

# ================= PREVIEW =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.preview (\d+)"))
async def preview_saved(event):
    index = int(event.pattern_match.group(1)) - 1
    with open(save_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if index < 0 or index >= len(lines):
        await event.respond("❌ Invalid index.")
        return
    await event.respond(f"📄 {lines[index]}")

# ================= DELETE =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.delete (\d+)"))
async def delete_saved(event):
    index = int(event.pattern_match.group(1)) - 1
    with open(save_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if index < 0 or index >= len(lines):
        await event.respond("❌ Invalid index.")
        return
    removed = lines.pop(index)
    with open(save_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
    await event.respond(f"✅ Deleted: {removed}")

# ================= AUTO REPLIES =================
@client.on(events.NewMessage(incoming=True))
async def auto_reply(event):
    if event.is_private and not event.out:
        user_id = event.sender_id
        now = datetime.now()

        # Spam check
        spam_tracker.setdefault(user_id, [])
        spam_tracker[user_id] = [t for t in spam_tracker[user_id] if (now - t).seconds < 60]
        spam_tracker[user_id].append(now)
        if len(spam_tracker[user_id]) > 2:
            await client.send_message(user_id, "⚠️ Don't Spam.")
            return

        # Gali filter
        bad_words = ["mc", "bc", "bkl"]
        if any(word in event.raw_text.lower() for word in bad_words):
            await event.delete()
            return

        # Offline auto-reply (1 per hour)
        last = last_reply_time.get(user_id)
        if not last or (now - last).seconds > 3600:
            if is_night():
                await client.send_message(user_id, "🌙 Abhi so raha hu, subah reply karunga.")
            else:
                await client.send_message(user_id, "📴 Abhi offline hu, thodi der baad reply karunga.")
            last_reply_time[user_id] = now

# ================= SCHEDULE DM =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.schedule (.+) (\d{1,2}:\d{2}) (.+)"))
async def schedule_msg(event):
    try:
        username = event.pattern_match.group(1)
        time_str = event.pattern_match.group(2)
        msg = event.pattern_match.group(3)

        now = datetime.now()
        target_time = datetime.strptime(time_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        if target_time < now:
            target_time += timedelta(days=1)

        delay = (target_time - now).total_seconds()

        await event.respond(f"⏰ Scheduled DM to {username} at {target_time.strftime('%H:%M')}:\n`{msg}`")

        async def send_later():
            await asyncio.sleep(delay)
            try:
                user = await client.get_entity(username)
                await client.send_message(user, msg)
            except Exception as e:
                await event.respond(f"❌ Failed to send DM: {str(e)}")

        task = asyncio.create_task(send_later())
        scheduled_tasks[username] = task
    except Exception as e:
        await event.respond(f"❌ Error: {str(e)}")

@client.on(events.NewMessage(outgoing=True, pattern=r"\.schedules"))
async def list_schedules(event):
    if not scheduled_tasks:
        await event.respond("📂 No scheduled DMs.")
        return
    msg = "📋 Scheduled DMs:\n"
    for user in scheduled_tasks.keys():
        msg += f"- {user}\n"
    await event.respond(msg)

@client.on(events.NewMessage(outgoing=True, pattern=r"\.cancel (.+)"))
async def cancel_schedule(event):
    user = event.pattern_match.group(1)
    task = scheduled_tasks.get(user)
    if task:
        task.cancel()
        scheduled_tasks.pop(user, None)
        await event.respond(f"❌ Cancelled DM to {user}")
    else:
        await event.respond("⚠️ No such scheduled DM found.")

# ================= START =================
client.start()
print("🚀 Userbot running...")
client.run_until_disconnected()