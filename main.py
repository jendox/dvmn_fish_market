import logging
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from dotenv import load_dotenv
from httpx import AsyncClient
from redis.asyncio import Redis
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import CallbackContext, Application, CommandHandler, CallbackQueryHandler, MessageHandler
from telegram.ext.filters import TEXT

from starapi import get_products, get_product, download_image, add_product_to_cart, get_cart_items, \
    CartItem, delete_cart_item, add_customer, Customer

logger = logging.getLogger("bot")


class BotState(StrEnum):
    START = "START"
    HANDLE_MENU = "HANDLE_MENU"
    HANDLE_DESCRIPTION = "HANDLE_DESCRIPTION"
    HANDLE_CART = "HANDLE_CART"
    WAITING_EMAIL = "WAITING_EMAIL"


@dataclass(frozen=True)
class AppConfig:
    starapi_url: str
    starapi_token: str
    bot_token: str
    redis_host: str
    redis_port: int
    redis_username: str
    redis_password: str

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_username}:{self.redis_password}@{self.redis_host}:{self.redis_port}"


def get_app_config() -> AppConfig:
    return AppConfig(
        starapi_url=os.getenv("STARAPI_URL", "http://localhost:1337"),
        starapi_token=os.environ["STARAPI_API_TOKEN"],
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        redis_host=os.environ["REDIS_HOST"],
        redis_port=int(os.environ["REDIS_PORT"]),
        redis_username=os.environ["REDIS_USERNAME"],
        redis_password=os.environ["REDIS_PASSWORD"],
    )


def _format_cart_message(items: list[CartItem]) -> str:
    if not items:
        return "🧺 Ваша корзина пока пуста."

    lines: list[str] = ["🧺 <b>Ваша корзина:</b>\n"]
    total = None

    for item in items:
        amount = item.amount
        title = item.title

        if item.price is not None:
            line_total = item.price * Decimal(str(amount))
            total = line_total if total is None else total + line_total

            lines.append(
                f"• {title}: {amount} кг × {item.price} руб. = <b>{line_total}</b> руб."
            )
        else:
            lines.append(f"• {title}: {amount} кг")

    if total is not None:
        lines.append(f"\n<b>Итого:</b> {total} руб.")

    return "\n".join(lines)


def _build_cart_keyboard(items: list[CartItem]) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(
            text=f"❌ Удалить: {item.title}",
            callback_data=f"remove_item:{item.document_id}"
        )]
        for item in items
    ]
    keyboard.extend([
        [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")],
        [InlineKeyboardButton("💳 Оплатить", callback_data="pay")],
    ])
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: CallbackContext) -> BotState:
    client = context.bot_data["http_client"]
    products = await get_products(client)
    if not products:
        await update.message.reply_text("К сожалению товары временно недоступны. Попробуйте позже.")
        return BotState.START

    keyboard = [
        [InlineKeyboardButton(product.title, callback_data=product.document_id)]
        for product in products
    ]
    keyboard.append([InlineKeyboardButton("🧺 Моя корзина", callback_data="my_cart")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text="Добро пожаловать в рыбный магазин! 🐟\nВыберите товар для подробной информации:",
        reply_markup=reply_markup,
    )
    return BotState.HANDLE_MENU


async def handle_menu(update: Update, context: CallbackContext) -> BotState:
    query: CallbackQuery = update.callback_query
    await query.answer()

    product_doc_id = query.data
    try:
        client = context.bot_data["http_client"]
        product = await get_product(product_doc_id, client)
        text = (
            f"🐟 <b>{product.title}</b>\n\n"
            f"💰 <b>Цена:</b> {product.price} руб./кг\n\n"
            f"📝 <b>Описание:</b>\n{product.description}\n\n"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Добавить в корзину", callback_data=f"add_to_cart:{product.document_id}")],
            [InlineKeyboardButton("🧺 Моя корзина", callback_data="my_cart")],
            [InlineKeyboardButton("⬅️ Вернуться к списку", callback_data="back_to_menu")],
        ])
        if product.picture_url:
            image_bytes = await download_image(product.picture_url, client)
            await query.message.chat.send_photo(
                photo=image_bytes,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await query.message.chat.send_message(
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        await query.message.chat.delete_message(query.message.message_id)
        return BotState.HANDLE_DESCRIPTION

    except Exception as exc:
        logger.error(f"Ошибка получения информации о продукте {product_doc_id}: {str(exc)}")
        await query.edit_message_text("Произошла ошибка при загрузке товара. Попробуйте позже.")
        return BotState.HANDLE_MENU


async def handle_description(update: Update, context: CallbackContext) -> BotState:
    query = update.callback_query
    client = context.bot_data["http_client"]

    data = query.data
    if data.startswith("add_to_cart:"):
        telegram_id = query.message.chat.id
        product_doc_id = data.split(":", 1)[1]
        try:
            await add_product_to_cart(telegram_id, product_doc_id, 1.0, client)
            await query.answer("🛒 Товар добавлен в корзину!")
        except Exception:
            await query.answer(
                "Не удалось добавить товар в корзину. Попробуйте позже."
            )
        return BotState.HANDLE_DESCRIPTION

    products = await get_products(client)
    if not products:
        await query.answer(
            "К сожалению товары временно недоступны. Попробуйте позже."
        )
        return BotState.HANDLE_MENU

    keyboard = [
        [InlineKeyboardButton(product.title, callback_data=product.document_id)]
        for product in products
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.chat.send_message(
        text="🐟 Выберите товар для подробной информации:",
        reply_markup=reply_markup,
    )
    await query.message.chat.delete_message(query.message.message_id)
    return BotState.HANDLE_MENU


async def handle_cart(update: Update, context: CallbackContext) -> BotState:
    client = context.bot_data["http_client"]
    query = update.callback_query

    chat = query.message.chat
    delete_message_id = query.message.message_id
    telegram_id = chat.id

    data = query.data
    if data == "pay":
        await query.answer()
        await chat.send_message("Введите ваш email для связи:")
        return BotState.WAITING_EMAIL

    if data.startswith("remove_item:"):
        cart_item_doc_id = data.split(":", 1)[1]
        try:
            await delete_cart_item(cart_item_doc_id, client)
            await query.answer("Товар удалён.")
        except Exception:
            await query.answer("Не удалось удалить товар. Попробуйте позже.")

    try:
        cart_items = await get_cart_items(telegram_id, client)
        text = _format_cart_message(cart_items)
        reply_markup = _build_cart_keyboard(cart_items)
    except Exception:
        text = "Не удалось загрузить корзину. Попробуйте позже."
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_menu")],
        ])

    await chat.send_message(text=text, reply_markup=reply_markup, parse_mode="HTML")
    try:
        await chat.delete_message(delete_message_id)
    except Exception:
        pass

    return BotState.HANDLE_CART


async def handle_email(update: Update, context: CallbackContext) -> BotState:
    chat = update.effective_chat
    text = update.message.text.strip() if update.message else None

    if not text:
        await chat.send_message("Пожалуйста, введите вашу почту текстом:")
        return BotState.WAITING_EMAIL

    if not re.match(r"^[^@\s]+@[^@\s]+\.[a-zA-Z0-9]+$", text):
        await chat.send_message("Это не похоже на email. Попробуйте ещё раз:")
        return BotState.WAITING_EMAIL

    user = update.effective_user
    client = context.bot_data["http_client"]
    customer = Customer(user.id, user.username, text)
    await add_customer(customer, client)
    await chat.send_message(f"Спасибо! Мы свяжемся с вами на {text}.")

    return BotState.START


async def handle_users_reply(update: Update, context: CallbackContext):
    redis: Redis = context.bot_data["redis"]

    if update.message is not None:
        user_reply = update.message.text
        chat_id = update.message.chat_id
    elif update.callback_query is not None:
        user_reply = update.callback_query.data
        chat_id = update.callback_query.message.chat.id
    else:
        return

    if user_reply == "/start":
        user_state = BotState.START
    elif user_reply == "back_to_menu":
        user_state = BotState.HANDLE_DESCRIPTION
    elif user_reply == "my_cart":
        user_state = BotState.HANDLE_CART
    elif user_reply.startswith("remove_item:"):
        user_state = BotState.HANDLE_CART
    elif user_reply == "pay":
        user_state = BotState.WAITING_EMAIL
    else:
        stored = await redis.get(str(chat_id))
        if stored is None:
            user_state = BotState.START
        else:
            user_state = BotState(stored.decode())

    state_handler = context.bot_data["states"][user_state]

    try:
        next_state: BotState = await state_handler(update, context)
        await redis.set(str(chat_id), str(next_state.value))
    except Exception as exc:
        logger.error(f"Ошибка: {str(exc)}")


async def post_init(application: Application):
    config: AppConfig = application.bot_data["config"]
    application.bot_data["http_client"] = AsyncClient(
        base_url=config.starapi_url,
        headers={"Authorization": f"Bearer {config.starapi_token}"},
        timeout=10.0,
    )
    application.bot_data["redis"] = Redis.from_url(config.redis_url)
    application.bot_data["states"] = {
        BotState.START: start,
        BotState.HANDLE_MENU: handle_menu,
        BotState.HANDLE_DESCRIPTION: handle_description,
        BotState.HANDLE_CART: handle_cart,
        BotState.WAITING_EMAIL: handle_email,
    }


async def post_shutdown(application: Application):
    client: AsyncClient = application.bot_data.get("http_client")
    redis: Redis = application.bot_data.get("redis")
    if redis is not None:
        await redis.aclose()
    if client is not None:
        await client.aclose()


def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    load_dotenv()
    config = get_app_config()

    application = (
        Application.builder()
        .token(token=config.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["config"] = config
    application.add_handler(CommandHandler("start", handle_users_reply))
    application.add_handler(CallbackQueryHandler(handle_users_reply))
    application.add_handler(MessageHandler(TEXT, handle_users_reply))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
