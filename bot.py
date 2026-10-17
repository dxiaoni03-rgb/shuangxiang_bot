import logging
import os
import time
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("shuangxiang_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment secret")
if not OWNER_ID_RAW.isdigit():
    raise RuntimeError("Missing/invalid OWNER_ID secret (numeric Telegram user ID required)")
OWNER_ID = int(OWNER_ID_RAW)


def get_forwarded_user_id(message) -> int | None:
    """Return the sender ID from a forwarded user message, when Telegram exposes it."""
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None
    sender_user = getattr(origin, "sender_user", None)
    if sender_user is not None:
        return sender_user.id
    # If the original user hid their identity, Telegram does not expose their ID.
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_user.id == OWNER_ID:
        await update.effective_message.reply_text(
            "双向机器人已启动。用户发来的消息会转发到这里；直接回复转发的用户消息即可回信。\n"
            "注意：本次 Actions 运行约 10 分钟，到时会自动离线。"
        )
    else:
        await update.effective_message.reply_text(
            "你好！请直接发送消息给我，管理员看到后会尽快回复。"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_user.id == OWNER_ID:
        text = "管理员用法：直接回复机器人转发到本聊天的用户消息，即可将回复发送给该用户。"
    else:
        text = "直接发送文字或媒体消息即可联系管理员。机器人仅在运行期间接收消息。"
    await update.effective_message.reply_text(text)


async def handle_owner_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.reply_to_message:
        await message.reply_text("请直接回复机器人转发给你的那条用户消息。")
        return

    target_user_id = get_forwarded_user_id(message.reply_to_message)
    if not target_user_id:
        await message.reply_text(
            "无法识别这条转发消息的原用户。对方可能隐藏了转发身份，或这不是机器人转发的原消息。"
        )
        return

    try:
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await message.reply_text("已发送给用户。")
    except TelegramError as exc:
        log.warning("Could not deliver admin reply to user %s: %s", target_user_id, exc)
        await message.reply_text("发送失败：用户可能已屏蔽机器人，或 Telegram 暂时不可用。")


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    if user.id == OWNER_ID:
        await handle_owner_reply(update, context)
        return
    try:
        await context.bot.forward_message(
            chat_id=OWNER_ID,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        # A short acknowledgement only; don't disclose the admin's ID.
        await message.reply_text("消息已转交管理员。")
    except TelegramError as exc:
        log.warning("Could not forward message from user %s: %s", user.id, exc)
        try:
            await message.reply_text("消息暂时未能发送，请稍后再试。")
        except TelegramError:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled bot error: %s", context.error)


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, handle_user_message))
    application.add_error_handler(error_handler)
    log.info("Bot polling started. Owner ID: %s", OWNER_ID)
    application.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
