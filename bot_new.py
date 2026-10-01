import asyncio
import os
from datetime import datetime, timedelta, timezone
import jdatetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from database import *
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
router = Router()
REWARD_STEP = 30
INVITE_DAYS = 7
def utc_now():
    return datetime.now(timezone.utc)

def jalali_datetime(dt):
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M")

def is_channel_member(member):
    return member.status == "member" or (member.status == "restricted" and member.is_member)
def user_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 لینک دعوت من", callback_data="my_link")],
        [InlineKeyboardButton(text="📊 آمار من", callback_data="my_stats")]
    ])
@router.message(CommandStart())
async def start_handler(message: Message, bot: Bot):
    user = message.from_user
    if not user:
        return
    now = utc_now()
    existing_user = await get_user(user.id)
    if not existing_user:
        await create_user(user.id, user.first_name or "", user.username, jalali_datetime(now))
    active_link = await get_active_invite(user.id, now.isoformat())
    if active_link:
        invite_link = active_link["invite_link"]
        expires_at = datetime.fromisoformat(active_link["expires_at"])
    else:
        expires_at = now + timedelta(days=INVITE_DAYS)
        invite = await bot.create_chat_invite_link(chat_id=CHANNEL_USERNAME, name=f"user_{user.id}", expire_date=int(expires_at.timestamp()), creates_join_request=False)
        invite_link = invite.invite_link
        invite_hash = invite_link.split("+")[-1]
        await save_invite_link(user.id, invite_link, invite_hash, now.isoformat(), expires_at.isoformat())
    count = await get_invite_count(user.id)
    remaining = REWARD_STEP - (count % REWARD_STEP)
    text = (
        "🎁 <b>لینک دعوت اختصاصی شما</b>\n\n"
        f"🔗 {invite_link}\n\n"
        f"⌛️ اعتبار لینک: <b>{INVITE_DAYS} روز</b>\n"
        f"📆 انقضا: <b>{jalali_datetime(expires_at)}</b>\n\n"
        f"📥 تعداد عضو شده: <b>{count} نفر</b>\n"
        f"🧸 تعداد باقی‌مانده تا جایزه: <b>{remaining} نفر</b>\n\n"
        "هر ۳۰ عضو جدید = یک گیفت «تدی» 🎁"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=user_keyboard())
@router.chat_member()
async def channel_member_update(event: ChatMemberUpdated, bot: Bot):
    if event.chat.username != CHANNEL_USERNAME.lstrip("@"):
        return
    if is_channel_member(event.old_chat_member) or not is_channel_member(event.new_chat_member):
        return
    if not event.invite_link:
        return
    invite_url = event.invite_link.invite_link
    invite = await get_invite_by_link(invite_url)
    if not invite:
        return
    invited_id = event.new_chat_member.user.id
    inviter_id = invite["owner_id"]
    if invited_id == inviter_id:
        return
    added = await add_referral(inviter_id, invited_id, invite["id"], utc_now().isoformat())
    if not added:
        return
    count = await get_invite_count(inviter_id)
    await update_user_invites(inviter_id)
    if count % REWARD_STEP == 0:
        reward_number = count // REWARD_STEP
        gift_code, _ = await create_reward(inviter_id, reward_number, utc_now().isoformat())
        text = (
            "🧸 <b>تبریک؛ یک گیفت «تدی» برنده شدی!</b>\n\n"
            "📭 زمان تحویل: <b>۱ الی ۱۲ ساعت آینده</b>\n"
            f"📥 تعداد عضو شده: <b>{count} نفر</b>\n"
            f"🏷️ کد هدیه: <code>{gift_code}</code>"
        )
    else:
        remaining = REWARD_STEP - (count % REWARD_STEP)
        text = (
            "🎉 تبریک؛ شما یک شخص جدید را دعوت کردید!\n\n"
            f"🧸 تعداد باقی‌مانده تا جایزه: <b>{remaining} نفر</b>\n"
            f"📥 تعداد عضو شده: <b>{count} نفر</b>"
        )
    try:
        await bot.send_message(inviter_id, text, parse_mode="HTML")
    except Exception as e:
        print(f"Referral notification error: {e}")
@router.message(Command("gift"))
async def gift_lookup(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("فرمت صحیح:\n/gift CODE")
        return
    code = parts[1].strip().upper()
    reward = await get_reward_by_code(code)
    if not reward:
        await message.answer("❌ این کد هدیه پیدا نشد.")
        return
    user = await get_user(reward["user_id"])
    username = "@" + user["username"] if user and user["username"] else "-"
    first_name = user["first_name"] if user else "-"
    joined_at = user["joined_at"] if user else "-"
    count = await get_invite_count(reward["user_id"])
    if reward["status"] == "pending":
        text = (
            f"👤 نام کاربر: {first_name}\n"
            f"🧸 تعداد بُردها: {reward["reward_number"]} بار\n"
            f"📥 تعداد عضو شده: {count} نفر\n"
            f"📆 تاریخ عضویت: {joined_at}\n\n"
            "✅ این کد هدیه معتبر و کاربر منتظر هدیه می‌باشد"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تایید هدیه", callback_data=f"confirm_reward:{code}")],
            [InlineKeyboardButton(text="👤 ورود به پروفایل کاربر", url=f"tg://user?id={reward["user_id"]}")]
        ])
    else:
        text = (
            f"👤 نام کاربر: {first_name}\n"
            f"🧸 تعداد بُردها: {reward["reward_number"]} بار\n"
            f"📥 تعداد عضو شده: {count} نفر\n"
            f"📆 تاریخ عضویت: {joined_at}\n\n"
            "❌ این کد هدیه منقضی و کاربر هدیه را دریافت کرده است."
        )
        keyboard = None
    await message.answer(text, reply_markup=keyboard)
@router.callback_query(F.data.startswith("confirm_reward:"))
async def confirm_reward_callback(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("دسترسی ندارید.", show_alert=True)
        return
    code = callback.data.split(":", 1)[1]
    reward = await get_reward_by_code(code)
    if not reward:
        await callback.answer("کد پیدا نشد.", show_alert=True)
        return
    if reward["status"] == "confirmed":
        await callback.answer("این هدیه قبلاً تایید شده است.", show_alert=True)
        return
    await confirm_reward(code, utc_now().isoformat())
    try:
        await bot.send_message(reward["user_id"], "🎁 <b>هدیه شما با موفقیت تایید و ثبت شد.</b>\n\n🧸 گیفت «تدی» شما آماده تحویل است. ❤️", parse_mode="HTML")
    except Exception as e:
        print(f"Gift notification error: {e}")
    await callback.answer("هدیه با موفقیت تایید شد ✅")
    await callback.message.edit_reply_markup(reply_markup=None)
@router.message(Command("status"))
async def status_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = await get_global_stats()
    text = (
        "📊 <b>آمار ربات</b>\n\n"
        f"👤 تعداد کاربران ربات: <b>{stats["users"]}</b>\n"
        f"🔗 تعداد لینک‌های فعال: <b>{stats["active_links"]}</b>\n"
        f"🔗 تعداد لینک‌های ساخته شده: <b>{stats["total_links"]}</b>\n"
        f"👥 تعداد کاربران دعوت شده: <b>{stats["invited_users"]}</b>\n"
        f"🧸 تعداد هدیه‌های دریافت شده: <b>{stats["confirmed_rewards"]}</b>"
    )
    await message.answer(text, parse_mode="HTML")



@router.callback_query(F.data == "my_link")
async def my_link_handler(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("ابتدا /start را بزنید.", show_alert=True)
        return
    invite = await get_active_invite(callback.from_user.id, utc_now().isoformat())
    if not invite:
        await callback.answer("لینک دعوت فعالی ندارید؛ /start را بزنید.", show_alert=True)
        return
    await callback.message.answer(f"🔗 <b>لینک دعوت شما:</b>\n{invite["invite_link"]}\n\n⏳ اعتبار تا: {jalali_datetime(datetime.fromisoformat(invite["expires_at"]))}", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "my_stats")
async def my_stats_handler(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("ابتدا /start را بزنید.", show_alert=True)
        return
    count = user["total_invites"]
    remaining = REWARD_STEP - (count % REWARD_STEP)
    await callback.message.answer(f"📊 <b>آمار شما</b>\n\n📥 تعداد عضو شده: <b>{count}</b> نفر\n🧸 تعداد باقی‌مانده تا جایزه: <b>{remaining}</b> نفر", parse_mode="HTML")
    await callback.answer()


async def expiry_watcher(bot):
    while True:
        try:
            now = utc_now().isoformat()
            expired = await get_expired_invites(now)

            for invite in expired:
                try:
                    await bot.send_message(
                        invite["owner_id"],
                        "⌛️ لینک دعوت شما منقضی شد!\n"
                        "جهت دریافت مجدد استارت را بزنید\n"
                        "/start"
                    )
                except Exception as e:
                    print(f"Expiry notification error: {e}")

            if expired:
                await deactivate_expired_invites(now)

        except Exception as e:
            print(f"Expiry watcher error: {e}")

        await asyncio.sleep(60)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

    await init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    watcher_task = asyncio.create_task(expiry_watcher(bot))

    print("================================")
    print("🤖 Baneh Referral Bot NEW")
    print("✅ Bot is running...")
    print(f"📢 Channel: {CHANNEL_USERNAME}")
    print("================================")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "chat_member", "callback_query"]
        )
    finally:
        watcher_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
