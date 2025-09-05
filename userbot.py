import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import PeerUser

# ================= CONFIG =================
load_dotenv()
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_string = os.getenv("SESSION")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",")]
db_path = os.getenv("DB_PATH", "bot_data.db")

save_file = "saved_items.txt"
if not os.path.exists(save_file):
    open(save_file, "w").close()

client = TelegramClient(StringSession(session_string), api_id, api_hash)

# ================= GLOBAL VARS =================
last_reply_time = {}  # track per-user autoreplies
scheduled_tasks = {}  # scheduled DMs
spam_tracker = {}     # spam control
spammer_running = False
spammer_task = None
spammer_text = ""
spammer_target = None

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
            await client.send_file("me", reply.media, caption=reply.text or "", as_copy=True)
        else:
            await client.send_message("me", reply.text or "")

        link_info = f"\n\n🔗 From: {chat_name} (ID: {chat_id})"
        await client.send_message("me", link_info)

        with open(save_file, "a", encoding="utf-8") as f:
            f.write((reply.text or "[Media]") + " | " + str(chat_id) + "\n")

        await event.respond("✅ Saved Successfully Boss.")
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
    if event.is_private and not event.out:  # Only DM
        user_id = event.sender_id
        now = datetime.now()

        # Spam check: more than 2 messages/min
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
                reply_msg = "🌙 Abhi so raha hu, subah reply karunga."
            else:
                reply_msg = "📴 Abhi offline hu, thodi der baad reply karunga."

            sent_msg = await client.send_message(user_id, reply_msg)
            last_reply_time[user_id] = now

            # Auto delete for everyone after sending
            async def check_delete():
                await asyncio.sleep(10)
                try:
                    await sent_msg.delete()
                except:
                    pass
            asyncio.create_task(check_delete())

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

        scheduled_tasks[username] = asyncio.create_task(send_later())
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

# ================= RAPID SPAMMER =================
@client.on(events.NewMessage(outgoing=True, pattern=r"\.start (.+)"))
async def start_spam(event):
    global spammer_running, spammer_task, spammer_text, spammer_target
    if spammer_running:
        await event.respond("⚠️ g@me already running. Use `.stop` first.")
        return
    spammer_text = event.pattern_match.group(1)
    spammer_target = event.chat_id
    spammer_running = True

    async def spam_loop():
        while spammer_running:
            await client.send_message(spammer_target, spammer_text)
            await asyncio.sleep(0.5)  # very fast

    spammer_task = asyncio.create_task(spam_loop())
    await event.respond("strted!")

@client.on(events.NewMessage(outgoing=True, pattern=r"\.stop"))
async def stop_spam(event):
    global spammer_running, spammer_task
    if spammer_running:
        spammer_running = False
        spammer_task.cancel()
        spammer_task = None
        await event.respond("Ok.")
    else:
        await event.respond("⚠️ No g@me running.")

# ================= START BOT =================
client.start()
print("🚀 Userbot running...")
client.run_until_disconnected()
