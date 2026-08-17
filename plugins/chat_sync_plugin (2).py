from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from telebot.apihelper import ApiTelegramException

import FunPayAPI.types
import handlers
import tg_bot.bot
from FunPayAPI.common.exceptions import ImageUploadError, MessageNotDeliveredError
from FunPayAPI.common.enums import MessageTypes, OrderStatuses
from FunPayAPI.updater.events import NewMessageEvent
from Utils import cardinal_tools

if TYPE_CHECKING:
    from cardinal import Cardinal
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, CallbackQuery, \
    ReplyKeyboardMarkup as RKM, KeyboardButton, User
from tg_bot import CBT, static_keyboards as skb, utils, keyboards
from locales.localizer import Localizer
from FunPayAPI.updater import events
from logging import getLogger
from threading import Thread
import telebot
import time
import json
import os
from PIL import Image
import io

NAME = "Chat Sync Plugin"
VERSION = "0.1.26"
DESCRIPTION = "Плагин, синхронизирующий FunPay чаты с Telegram чатом (форумом).\n\nОтправляй сообщение в нужную тему - оно будет отправляться в нужный FunPay чат! И наоборот!"
CREDITS = "@woopertail, @sidor0912"
UUID = "745ed27e-3196-47c3-9483-e382c09fd2d8"
SETTINGS_PAGE = True
PLUGIN_FOLDER = f"storage/plugins/{UUID}/"

SPECIAL_SYMBOL = "⁢"
MIN_BOTS = 4
BOT_DELAY = 4
LOGGER_PREFIX = "[CHAT SYNC PLUGIN]"
logger = getLogger("FPC.shat_sync")

localizer = Localizer()
_ = localizer.translate

# CALLBACKS
ADD_SYNC_BOT = "sync_plugin.add_bot"
CBT_SWITCH = "sync_plugin.switch"
CBT_SWITCHERS = "sync_plugin.switchers"
DELETE_SYNC_BOT = "sync_plugin.delete_bot"
BOT_ACTION = "sync_plugin.bot_action"
SETUP_SYNC_CHAT = "sync_plugin.setup_chat"
DELETE_SYNC_CHAT = "sync_plugin.delete_chat"
PLUGIN_NO_BUTTON = "sunc_plugin.no"


# KEYBOARDS
def plugin_settings_kb(cs: ChatSync, offset: int, checked_bots: dict[int, str] | None) -> K:
    kb = K()
    if cs.ready:
        kb.add(B(_("pl_settings"), callback_data=f"{CBT_SWITCHERS}:{offset}"))
    bots = cs.bots if checked_bots is None else [cs.tgbot, *cs.bots]
    for index, bot in enumerate(bots):
        is_main_bot = getattr(bot, "main_cs_bot", False)
        try:
            data = cs.bot_get_me(bot)
            username = data.username
            name = data.full_name.split("ㅤ")[0].strip() if is_main_bot else f"@{username}"
            id_ = data.id
        except:
            id_ = None
            name = None
            username = None

        row = [B(name if name else f"⚠️ {bot.token}", url=f"https://t.me/{username if username else 'sidor_donate'}"),]
        if checked_bots and id_:
            b_url = None
            action = checked_bots.get(id_)
            if action == "add":
                b_url = f"https://t.me/{username}?startgroup"
                b_text = "➕"
            elif action == "error":
                b_text = "💥"
            elif action == "ok":
                b_text = "✅"
            elif action == "rights":
                b_text = "📛"
            elif action == "admin":
                b_text = "🔒"
            else:
                b_text = "❔"
                b_url = "https://t.me/sidor_donate"

            row.append(B(b_text, url=b_url, callback_data=f"{BOT_ACTION}:{action}" if not b_url else None))
        if not is_main_bot:
            row.append(B("🗑️", callback_data=f"{DELETE_SYNC_BOT}:{index}:{offset}"))
        kb.row(*row)
    kb.add(B("➕ Добавить Telegram бота", callback_data=f"{ADD_SYNC_BOT}:{offset}"))
    kb.add(B(_("gl_refresh"), callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
    kb.add(B(_("gl_back"), callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:{offset}"))
    return kb


def switchers_kb(cs: ChatSync, offset: int) -> K:
    kb = K()
    kb.add(B(("🟢" if cs.settings["watermark_is_hidden"] else "🔴") + " Скрывать вотермарку",
             callback_data=f"{CBT_SWITCH}:watermark_is_hidden:{offset}"))
    kb.add(B(("🟢" if cs.settings["ad"] else "🔴") + " Рекламные сообщения FunPay",
             callback_data=f"{CBT_SWITCH}:ad:{offset}"))
    kb.add(B(_("mv_show_image_name", ("🟢" if cs.settings["image_name"] else "🔴")),
             callback_data=f"{CBT_SWITCH}:image_name:{offset}"))
    kb.add(B(("🟢" if cs.settings["mono"] else "🔴") + " Моно шрифт",
             callback_data=f"{CBT_SWITCH}:mono:{offset}"))
    kb.add(B(("🟢" if cs.settings["chat_url"] else "🔴") + " Ссылка на чат",
             callback_data=f"{CBT_SWITCH}:chat_url:{offset}"))
    kb.add(B(("🟢" if cs.settings["edit_topic"] else "🔴") + " Изменять название и иконку темы",
             callback_data=f"{CBT_SWITCH}:edit_topic:{offset}"))
    kb.add(B(("🟢" if cs.settings["buyer_viewing"] else "🔴") + " Покупатель смотрит",
             callback_data=f"{CBT_SWITCH}:buyer_viewing:{offset}"))
    kb.add(B(("🟢" if cs.settings["templates"] else "🔴") + " Заготовки ответов",
             callback_data=f"{CBT_SWITCH}:templates:{offset}"))
    kb.add(B(("🟢" if cs.settings["self_notify"] else "🔴") + " Уведомление при сообщении от меня",
             callback_data=f"{CBT_SWITCH}:self_notify:{offset}"))
    kb.add(B(("🟢" if cs.settings["tag_admins_on_reply"] else "🔴") + " @ при сообщении собеседника",
             callback_data=f"{CBT_SWITCH}:tag_admins_on_reply:{offset}"))
    kb.add(B(_("gl_back"), callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
    return kb


def templates_kb(cs: ChatSync) -> RKM | telebot.types.ReplyKeyboardRemove:
    if not cs.settings["templates"]:
        return telebot.types.ReplyKeyboardRemove()
    btns = [KeyboardButton(f"{SPECIAL_SYMBOL}{i}){SPECIAL_SYMBOL} {tpl}") for i, tpl
            in enumerate(cs.cardinal.telegram.answer_templates, start=1)]
    markup = RKM(resize_keyboard=True, row_width=1)
    markup.add(*btns)
    return markup


def back_keyboard(offset: int) -> K:
    return K().add(B(_("gl_back"), callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))


def setup_chat_keyboard() -> K:
    return K().row(B(_("gl_yes"), callback_data=SETUP_SYNC_CHAT),
                   B(_("gl_no"), callback_data=PLUGIN_NO_BUTTON))


def delete_chat_keyboard() -> K:
    return K().row(B(_("gl_yes"), callback_data=DELETE_SYNC_CHAT),
                   B(_("gl_no"), callback_data=PLUGIN_NO_BUTTON))


class ChatSync:
    def __init__(self, crd: Cardinal):
        self.cardinal = crd
        self.settings: dict | None = None
        self.threads: dict | None = None
        """str(фп айди чата): айди темы"""
        self.__reversed_threads: dict | None = None
        """айди темы: str(фп айди чата)"""
        self.photos_mess: dict[int | str, list[telebot.types.Message]] = {}
        self.bots: list[telebot.TeleBot] | None = None
        self.current_bot: telebot.TeleBot | None = None
        self.initialized = False  # Боты, настройки и топики загружены без ошибок.
        self.ready = False  # Все условия для начала работы соблюдены (привязан чат, ботов 4 или больше).
        self.plugin_uuid = UUID
        self.tg = None
        self.tgbot = None
        if self.cardinal.telegram:
            self.tg = self.cardinal.telegram
            self.tgbot = self.tg.bot
            setattr(self.tgbot, "main_cs_bot", True)
        self.notification_last_stack_id = ""
        self.attributation_last_stack_id = ""
        self.sync_chats_running = False
        self.full_history_running = False
        self.init_chat_synced = False
        # id чата - время последнего сообщения
        self.chats_time = {}

        # {ID темы: (id эмодзи топика, заголовок топика)}
        self.threads_info = {}
        self.__recheck_bots = False

        setattr(ChatSync.send_message, "plugin_uuid", UUID)
        setattr(ChatSync.ingoing_message_handler, "plugin_uuid", UUID)
        setattr(ChatSync.new_order_handler, "plugin_uuid", UUID)
        setattr(ChatSync.sync_chat_on_start_handler, "plugin_uuid", UUID)
        setattr(ChatSync.setup_event_attributes, "plugin_uuid", UUID)

    def threads_pop(self, fp_chat_id: int | str):
        thread_id = self.threads.pop(str(fp_chat_id), None)
        self.__reversed_threads.pop(thread_id, None)

    def new_thread(self, fp_chat_id: int | str, thread_id: int | str):
        self.threads[str(fp_chat_id)] = int(thread_id)
        self.__reversed_threads[int(thread_id)] = str(fp_chat_id)

    def load_settings(self):
        """
        Загружает настройки плагина.
        """
        self.settings = {"chat_id": None,
                         "watermark_is_hidden": False,
                         "ad": True,
                         "image_name": True,
                         "chat_url": False,
                         "mono": False,
                         "buyer_viewing": True,
                         "edit_topic": True,
                         "templates": False,
                         "self_notify": True,
                         "tag_admins_on_reply": False}
        if not os.path.exists(os.path.join(PLUGIN_FOLDER, "settings.json")):
            logger.warning(f"{LOGGER_PREFIX} Файл с настройками не найден.")
        else:
            with open(os.path.join(PLUGIN_FOLDER, "settings.json"), "r", encoding="utf-8") as f:
                self.settings.update(json.loads(f.read()))
            logger.info(f"{LOGGER_PREFIX} Загрузил настройки.")

    def load_threads(self):
        """
        Загружает список Telegram-топиков.
        """
        if not os.path.exists(os.path.join(PLUGIN_FOLDER, "threads.json")):
            logger.warning(f"{LOGGER_PREFIX} Файл с данными о Telegram топиках не найден.")
            self.threads = {}
            self.__reversed_threads = {}
        else:
            with open(os.path.join(PLUGIN_FOLDER, "threads.json"), "r", encoding="utf-8") as f:
                self.threads = json.loads(f.read())
                self.__reversed_threads = {v: k for k, v in self.threads.items()}
            logger.info(f"{LOGGER_PREFIX} Загрузил данные о Telegram топиках.")

    def load_bots(self):
        """
        Загружает и инициализирует Telegram ботов.
        """
        if not os.path.exists(os.path.join(PLUGIN_FOLDER, "bots.json")):
            logger.warning(f"{LOGGER_PREFIX} Файл с токенами Telegram-ботов не найден.")
            self.bots = []
            return

        with open(os.path.join(PLUGIN_FOLDER, "bots.json"), "r", encoding="utf-8") as f:
            tokens = json.loads(f.read())

        bots = []
        for num, i in enumerate(tokens):
            bot = telebot.TeleBot(i, parse_mode="HTML", allow_sending_without_reply=True)
            try:
                data = self.bot_get_me(bot)
                logger.info(f"{LOGGER_PREFIX} Бот @{data.username} инициализирован.")
                bots.append(bot)
            except:
                logger.error(
                    f"{LOGGER_PREFIX} Произошла ошибка при инициализации Telegram бота с токеном $YELLOW{i}$RESET.")
                logger.debug("TRACEBACK", exc_info=True)
                continue
            try:
                if data.full_name != SPECIAL_SYMBOL:
                    bot.set_my_name(SPECIAL_SYMBOL)
                    time.sleep(0.5)
                sh_text = "🛠️ github.com/sidor0912/FunPayCardinal 💰 @sidor_donate 👨‍💻 @sidor0912 🧩 @fpc_plugins 🔄 @fpc_updates 💬 @funpay_cardinal"
                res = bot.get_my_short_description().short_description
                if res != sh_text:
                    bot.set_my_short_description(sh_text)
                for i in [None, *localizer.languages.keys()]:
                    res = bot.get_my_description(i).description
                    text = _("adv_description", self.cardinal.VERSION, language=i)
                    d = {"Telegram": "TG",
                         "панель управління": "ПУ",
                         "панель управления": "ПУ",
                         "control panel": "CP",
                         "...": ""}
                    for k, v in d.items():
                        text = text.replace(k, v)
                    f, s = text.split("🌟 ", maxsplit=1)
                    s = s.split(" ", maxsplit=1)[-1]
                    s = s[0].upper() + s[1:]
                    text = f"{f}🌟 {s}" + _(f"{UUID}_bot_num", num + 1, language=i)
                    if res != text:
                        bot.set_my_description(text, language_code=i)
            except:
                logger.warning(
                    f"{LOGGER_PREFIX} Произошла ошибка при изменении Telegram бота $YELLOW{data.username}$RESET.")
                logger.debug("TRACEBACK", exc_info=True)

        logger.info(f"{LOGGER_PREFIX} Инициализация ботов завершена. Ботов инициализировано: $YELLOW{len(bots)}$RESET.")
        self.bots = bots
        self.current_bot = self.bots[0] if self.bots else None

    def save_threads(self):
        """
        Сохраняет Telegram-топики.
        """
        if not os.path.exists(PLUGIN_FOLDER):
            os.makedirs(PLUGIN_FOLDER)
        with open(os.path.join(PLUGIN_FOLDER, "threads.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(self.threads))

    def save_settings(self):
        """
        Сохраняет настройки.
        """
        if not os.path.exists(PLUGIN_FOLDER):
            os.makedirs(PLUGIN_FOLDER)
        with open(os.path.join(PLUGIN_FOLDER, "settings.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(self.settings))

    def save_bots(self):
        """
        Сохраняет токены ботов.
        """
        if not os.path.exists(PLUGIN_FOLDER):
            os.makedirs(PLUGIN_FOLDER)
        with open(os.path.join(PLUGIN_FOLDER, "bots.json"), "w", encoding="utf-8") as f:
            data = [i.token for i in self.bots]
            f.write(json.dumps(data, ensure_ascii=False))

    @classmethod
    def bot_get_me(cls, bot: telebot.TeleBot) -> User:
        if not getattr(bot, "me", None):
            me = bot.get_me()
            setattr(bot, "me", me)
        return getattr(bot, "me", None)

    def swap_curr_bot(self):
        """
        Переключает текущего бота на следующего.
        """
        if not self.current_bot and not self.bots:
            return
        try:
            self.current_bot = self.bots[self.bots.index(self.current_bot) + 1]
        except IndexError:
            self.current_bot = self.bots[0]

    def is_outgoing_message(self, m: telebot.types.Message) -> bool:
        if self.settings["chat_id"] and m.chat.id == self.settings["chat_id"] and \
                m.reply_to_message and m.reply_to_message.forum_topic_created:
            if m.entities:
                for i in m.entities:
                    if i.type == "bot_command" and i.offset == 0:
                        return False
            return True
        return False

    def is_template_message(self, m: telebot.types.Message) -> bool:
        if self.settings["chat_id"] and m.chat.id == self.settings["chat_id"] \
                and m.reply_to_message and m.reply_to_message.is_topic_message \
                and m.reply_to_message.from_user.is_bot \
                and m.reply_to_message.from_user.first_name == SPECIAL_SYMBOL \
                and m.text \
                and m.text.startswith(SPECIAL_SYMBOL):
            # todo проверка, что автор в self.bots?
            # todo проверка, что сообщение начинается с f"{SPECIAL_SYMBOL}ЧИСЛО){SPECIAL_SYMBOL} "
            return True
        return False

    def is_error_message(self, m: telebot.types.Message):
        if self.settings["chat_id"] and m.chat.id == self.settings["chat_id"] \
                and m.reply_to_message and m.message_thread_id in self.__reversed_threads \
                and not m.reply_to_message.forum_topic_created:
            return True
        return False

    def new_synced_chat(self, chat_id: int, chat_name: str) -> bool:
        try:
            topic = self.current_bot.create_forum_topic(self.settings["chat_id"], f"{chat_name} ({chat_id})",
                                                        icon_custom_emoji_id="5417915203100613993")
            self.swap_curr_bot()
            self.new_thread(chat_id, topic.message_thread_id)
            self.save_threads()
            logger.info(
                f"{LOGGER_PREFIX} FunPay чат $YELLOW{chat_name} (CID: {chat_id})$RESET связан с Telegram темой $YELLOW{topic.message_thread_id}$RESET.")
            try:
                text = f"<a href='https://funpay.com/chat/?node={chat_id}'>{chat_name}</a>\n\n" \
                       f"<a href='https://funpay.com/orders/trade?buyer={chat_name}'>Продажи</a> | " \
                       f"<a href='https://funpay.com/orders/?seller={chat_name}'>Покупки</a>"
                self.current_bot.send_message(self.settings["chat_id"], text, message_thread_id=topic.message_thread_id,
                                              reply_markup=templates_kb(self))
                self.swap_curr_bot()
            except:
                logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправке первого сообщения при создании топика.")
                logger.debug("TRACEBACK", exc_info=True)

            return True
        except:
            logger.error(f"{LOGGER_PREFIX} Произошла ошибка при связывании FunPay чата с Telegram темой.")
            logger.debug("TRACEBACK", exc_info=True)
            return False

    # HANDLERS
    # pre init
    def load(self):
        try:
            d = {"ru": "\n\nБот плагина #chat_sync №{}",
                 "uk": "\n\nБот плагіна #chat_sync №{}",
                 "en": "\n\nBot of plugin #chat_sync №{}"}
            for k, v in localizer.languages.items():
                setattr(v, f"{UUID}_bot_num", d[k])
            self.load_settings()
            self.load_threads()
            self.load_bots()
        except:
            logger.error(f"{LOGGER_PREFIX} Произошла ошибка при инициализации плагина.")
            logger.debug("TRACEBACK", exc_info=True)
            return
        logger.info(f"{LOGGER_PREFIX} Плагин инициализирован.")
        self.initialized = True

        if self.settings["chat_id"] and len(self.bots) >= MIN_BOTS and not self.cardinal.old_mode_enabled:
            self.ready = True

    def setup_event_attributes(self, c: Cardinal, e: events.NewMessageEvent):
        if e.stack.id() == self.attributation_last_stack_id:
            return
        self.attributation_last_stack_id = e.stack.id()
        for event in e.stack.get_stack():
            if event.message.text and event.message.text.startswith(SPECIAL_SYMBOL):
                event.message.text = event.message.text.replace(SPECIAL_SYMBOL, "")
                if event.message.author_id == c.account.id:
                    setattr(event, "sync_ignore", True)

    def replace_handler(self):
        if not self.initialized:
            return
        for index, handler in enumerate(self.cardinal.new_message_handlers):
            if handler.__name__ == "send_new_msg_notification_handler":
                break
        self.cardinal.new_message_handlers.insert(index, self.ingoing_message_handler)
        self.cardinal.new_message_handlers.insert(0, self.setup_event_attributes)
        self.cardinal.new_order_handlers.insert(0, self.new_order_handler)
        self.cardinal.init_message_handlers.append(self.sync_chat_on_start_handler)

    def bind_tg_handlers(self):
        if not self.initialized:
            return
        self.tg.cbq_handler(self.open_switchers_menu, lambda c: c.data.startswith(CBT_SWITCHERS))
        self.tg.cbq_handler(self.switch, lambda c: c.data.startswith(CBT_SWITCH))
        self.tg.cbq_handler(self.open_settings_menu, lambda c: c.data.startswith(f"{CBT.PLUGIN_SETTINGS}:{UUID}:"))
        self.tg.cbq_handler(self.act_add_sync_bot, lambda c: c.data.startswith(ADD_SYNC_BOT))
        self.tg.cbq_handler(self.delete_sync_bot, lambda c: c.data.startswith(DELETE_SYNC_BOT))
        self.tg.cbq_handler(self.bot_action, lambda c: c.data.startswith(BOT_ACTION))
        self.tg.cbq_handler(self.confirm_setup_sync_chat, lambda c: c.data == SETUP_SYNC_CHAT)
        self.tg.cbq_handler(self.confirm_delete_sync_chat, lambda c: c.data == DELETE_SYNC_CHAT)
        self.tg.cbq_handler(self.no, lambda c: c.data == PLUGIN_NO_BUTTON)
        self.tg.msg_handler(self.add_sync_bot,
                            func=lambda m: self.tg.check_state(m.chat.id, m.from_user.id, ADD_SYNC_BOT))
        self.tg.msg_handler(self.send_funpay_image, content_types=["photo", "document"],
                            func=lambda m: self.is_outgoing_message(m))
        self.tg.msg_handler(self.send_funpay_sticker, content_types=["sticker"],
                            func=lambda m: self.is_outgoing_message(m))
        self.tg.msg_handler(self.send_message, func=lambda m: self.is_outgoing_message(m))
        self.tg.msg_handler(self.send_template, func=lambda m: self.is_template_message(m))
        self.tg.msg_handler(self.send_message_error, content_types=["photo", "document", "sticker", "text"],
                            func=lambda m: self.is_error_message(m))
        self.tg.msg_handler(self.setup_sync_chat, commands=["setup_sync_chat"])
        self.tg.msg_handler(self.delete_sync_chat, commands=["delete_sync_chat"])
        self.tg.msg_handler(self.sync_chats, commands=["sync_chats"])
        self.tg.msg_handler(self.watch_handler, commands=["watch"])
        self.tg.msg_handler(self.history_handler, commands=["history"])
        self.tg.msg_handler(self.full_history_handler, commands=["full_history"])
        self.tg.msg_handler(self.templates_handler, commands=["templates"])

        self.cardinal.add_telegram_commands(UUID, [
            ("setup_sync_chat", "Активировать группу для синхронизации", True),
            ("delete_sync_chat", "Деактивировать группу для синхронизации", True),
            ("sync_chats", "Ручная синхронизация чатов", True),
            ("watch", "Что сейчас смотрит пользователь?", True),
            ("history", "Последние 25 сообщений чата", True),
            ("full_history", "Полная история чата", True),
            ("templates", "Заготовки ответов", True)
        ])

    def edit_icon_and_topic_name(self, c: Cardinal, e: events.NewMessageEvent, chat_id, chat_name, thread_id):
        try:
            str4topic = ""
            if not e.message.is_employee and not \
                    (e.message.type in (MessageTypes.REFUND, MessageTypes.ORDER_PURCHASED, MessageTypes.ORDER_CONFIRMED,
                                        MessageTypes.ORDER_REOPENED, MessageTypes.REFUND_BY_ADMIN,
                                        MessageTypes.ORDER_CONFIRMED_BY_ADMIN, MessageTypes.PARTIAL_REFUND) and
                     not e.message.i_am_buyer):
                return
            if time.time() - c.account.last_429_err_time < 5 * 60:
                return
            if e.message.author_id == 500 and e.message.chat_name != e.message.author:
                return
            sales = []
            start_from = None
            locale = None
            subcs = None
            while True:
                start_from, sales_temp, locale, subcs = c.account.get_sales(buyer=chat_name, start_from=start_from,
                                                                            locale=locale, sudcategories=subcs)
                sales.extend(sales_temp)
                if start_from is None:
                    break
                time.sleep(1)
            paid = 0
            refunded = 0
            closed = 0
            paid_sum = {}
            refunded_sum = {}
            closed_sum = {}
            for sale in sales:
                if sale.status == OrderStatuses.REFUNDED:
                    refunded += 1
                    refunded_sum[sale.currency] = refunded_sum.get(sale.currency, 0) + sale.price
                elif sale.status == OrderStatuses.PAID:
                    paid += 1
                    paid_sum[sale.currency] = paid_sum.get(sale.currency, 0) + sale.price
                elif sale.status == OrderStatuses.CLOSED:
                    closed += 1
                    closed_sum[sale.currency] = closed_sum.get(sale.currency, 0) + sale.price
            paid_sum = ", ".join(sorted([f"{round(v, 2)}{k}" for k, v in paid_sum.items()], key=lambda x: x[-1]))
            refunded_sum = ", ".join(
                sorted([f"{round(v, 2)}{k}" for k, v in refunded_sum.items()], key=lambda x: x[-1]))
            closed_sum = ", ".join(sorted([f"{round(v, 2)}{k}" for k, v in closed_sum.items()], key=lambda x: x[-1]))

            if e.message.is_employee and e.message.chat_name == e.message.author:
                icon_custom_emoji_id = "5377494501373780436"
            elif (
                    e.message.type == MessageTypes.ORDER_REOPENED or e.message.is_moderation or e.message.is_arbitration or (
                    e.message.is_support and any(
                [arb in e.message.text.lower() for arb in ("арбитраж", "арбітраж", "arbitration")]))) and paid:
                icon_custom_emoji_id = "5377438129928020693"
            elif chat_name in c.blacklist:
                icon_custom_emoji_id = "5238234236955148254"
            elif e.message.is_employee:
                return
            elif paid:
                icon_custom_emoji_id = "5431492767249342908"
            elif closed >= 50:
                icon_custom_emoji_id = "5357107601584693888"
            elif closed >= 10:
                icon_custom_emoji_id = "5309958691854754293"
            elif closed:
                icon_custom_emoji_id = "5350452584119279096"
            elif refunded:
                icon_custom_emoji_id = "5312424913615723286"
            else:
                icon_custom_emoji_id = "5417915203100613993"
            if paid or closed or refunded:
                str4topic = f"{paid}|{closed}|{refunded}👤{chat_name} ({chat_id})"
            elif e.message.badge is not None:
                str4topic = f"{chat_name} ({chat_id})"
            else:
                return
            if self.threads_info.get(thread_id) == (icon_custom_emoji_id, str4topic):
                return
            if self.settings["edit_topic"] and self.current_bot.edit_forum_topic(name=str4topic,
                                                                                 chat_id=self.settings["chat_id"],
                                                                                 message_thread_id=thread_id,
                                                                                 icon_custom_emoji_id=icon_custom_emoji_id):
                self.threads_info[thread_id] = (icon_custom_emoji_id, str4topic)
                self.swap_curr_bot()
            if e.message.author_id == 0:
                txt4tg = f"Статистика по пользователю <b>{chat_name}</b>\n\n" \
                         f"<b>🛒 Оплачен:</b> <code>{paid}</code> {'(<code>' + paid_sum + '</code>)' if paid_sum else ''}\n" \
                         f"<b>🏁 Закрыт:</b> <code>{closed}</code> {'(<code>' + closed_sum + '</code>)' if closed_sum else ''}\n" \
                         f"<b>🔙 Возврат:</b> <code>{refunded}</code> {'(<code>' + refunded_sum + '</code>)' if refunded_sum else ''}"
                self.current_bot.send_message(self.settings["chat_id"], txt4tg, message_thread_id=thread_id,
                                              reply_markup=templates_kb(self))
                self.swap_curr_bot()
        except Exception as e:
            logger.error(
                f"{LOGGER_PREFIX} Произошла ошибка при изменении иконки/названия чата {thread_id} на {str4topic}")
            logger.debug("TRACEBACK", exc_info=True)
            if isinstance(e, telebot.apihelper.ApiTelegramException) and e.result.status_code == 400 and \
                    "message thread not found" in str(e):
                self.threads_pop(chat_id)
                self.save_threads()

    # new message
    def ingoing_message(self, c: Cardinal, e: events.NewMessageEvent):
        chat_id, chat_name = e.message.chat_id, e.message.chat_name
        if str(chat_id) not in self.threads:
            if not self.new_synced_chat(chat_id, chat_name):
                return

        events_list = [e for e in e.stack.get_stack() if not hasattr(e, "sync_ignore")]
        if not events_list:
            return
        tags = " " + " ".join([f"<a href='tg://user?id={i}'>{SPECIAL_SYMBOL}</a>" for i in c.telegram.authorized_users])
        thread_id = self.threads[str(chat_id)]
        text = ""
        last_message_author_id = -1
        last_by_bot = False
        last_badge = None
        last_by_vertex = False
        to_tag = False
        only_self_messages = True
        for i in events_list:
            if self.settings["edit_topic"]:
                Thread(target=self.edit_icon_and_topic_name, args=(c, i, chat_id, chat_name, thread_id),
                       daemon=True).start()
            if self.settings["buyer_viewing"] and (
                    time.time() - self.chats_time.get(i.message.chat_id, 0)) > 24 * 3600 and \
                    time.time() - c.account.last_429_err_time > 5 * 60:
                self.chats_time[i.message.chat_id] = time.time()
                looking_text = ""
                looking_link = ""
                try:
                    bv = self.cardinal.account.get_buyer_viewing(i.message.interlocutor_id)
                    looking_text = bv.text
                    looking_link = bv.link
                except Exception as e:
                    logger.error(
                        f"{LOGGER_PREFIX} Произошла ошибка при получении данных чата $YELLOW{e.message.chat_name} (CID: {chat_id})$RESET.")
                    logger.debug("TRACEBACK", exc_info=True)
                if looking_text and looking_link:
                    text += f"<b><i>Смотрит: </i></b> <a href=\"{looking_link}\">{utils.escape(looking_text)}</a>\n\n"

            message_text = str(i.message)

            if not any([c.bl_cmd_notification_enabled and i.message.author in c.blacklist,
                        (command := message_text.strip().lower()) not in c.AR_CFG]):
                if c.AR_CFG[command].getboolean("telegramNotification"):
                    to_tag = True

            if i.message.author_id != c.account.id:
                only_self_messages = False

            if i.message.is_employee and (i.message.author_id != 500 or i.message.interlocutor_id == 500):
                to_tag = True

            if (self.settings["tag_admins_on_reply"] and not i.message.is_autoreply and
                    (i.message.author_id == i.message.interlocutor_id or
                     (i.message.author_id == 0 and
                      i.message.type == MessageTypes.ORDER_PURCHASED and
                      i.message.i_am_seller))):
                to_tag = True

            author_text = i.message.author if not self.settings["chat_url"] else \
                f"<a href='https://funpay.com/chat/?node={i.message.chat_id}'>{i.message.author}</a>"
            if i.message.author_id == last_message_author_id and i.message.by_bot == last_by_bot \
                    and i.message.badge == last_badge and text != "" and last_by_vertex == i.message.by_vertex:
                author = ""
            elif i.message.author_id == c.account.id:
                author = f"<i><b>🤖 FPC:</b></i> " if i.message.by_bot else f"<i><b>🫵 {_('you')}:</b></i> "
                if i.message.is_autoreply:
                    author = f"<i><b>📦 {_('you')} ({i.message.badge}):</b></i> "
            elif i.message.author_id == 0:
                author = f"<i><b>🔵 {author_text}: </b></i>"
            elif i.message.is_employee:
                if i.message.author_id == 500 and i.message.interlocutor_id != 500:
                    if self.settings["ad"]:
                        author = f"<i><b>📣 {author_text} ({i.message.badge}): </b></i>"
                    else:
                        continue
                else:
                    author = f"<i><b>🆘 {author_text} ({i.message.badge}): </b></i>"
            elif i.message.author == i.message.chat_name:
                author = f"<i><b>👤 {author_text}: </b></i>"
                if i.message.is_autoreply:
                    author = f"<i><b>🛍️ {author_text} ({i.message.badge}):</b></i> "
                elif i.message.author in self.cardinal.blacklist:
                    author = f"<i><b>🚷 {author_text}: </b></i>"
                elif i.message.by_bot:
                    author = f"<i><b>🐦 {author_text}: </b></i>"
                elif i.message.by_vertex:
                    author = f"<i><b>🐺 {author_text}: </b></i>"
            else:
                author = f"<i><b>🆘 {author_text} {_('support')}: </b></i>"

            if not i.message.text:
                img_name = self.settings.get('image_name') and \
                           not (i.message.author_id == c.account.id and i.message.by_bot) and \
                           i.message.image_name
                msg_text = f"<a href=\"{message_text}\">{img_name or _('photo')}</a>"
            elif i.message.author_id == 0:
                msg_text = f"<b><i>{utils.escape(message_text)}</i></b>"
            else:
                hidden_wm = False
                if i.message.author_id == c.account.id and i.message.by_bot and \
                        (wm := c.MAIN_CFG["Other"].get("watermark", "")) and \
                        self.settings.get("watermark_is_hidden") and \
                        message_text.startswith(f"{wm}\n"):
                    msg_text = message_text.replace(wm, "", 1)
                    hidden_wm = True
                else:
                    msg_text = message_text
                msg_text = utils.escape(msg_text)
                msg_text = f"<code>{msg_text}</code>" if self.settings["mono"] else msg_text
                msg_text = f"<tg-spoiler>🐦</tg-spoiler>{msg_text}" if hidden_wm else msg_text

            text += f"{author}{msg_text}\n\n"
            last_message_author_id = i.message.author_id
            last_by_bot = i.message.by_bot
            last_badge = i.message.badge
            last_by_vertex = i.message.by_vertex
            if not i.message.text:
                try:
                    tag_text = tags if to_tag else ""
                    to_tag = False
                    text = f"<a href=\"{message_text}\">{SPECIAL_SYMBOL}</a>" + text + tag_text
                    self.current_bot.send_message(self.settings["chat_id"], text.rstrip(), message_thread_id=thread_id,
                                                  reply_markup=templates_kb(self),
                                                  disable_notification=not self.settings["self_notify"] and only_self_messages)
                    self.swap_curr_bot()
                    text = ""
                    only_self_messages = True
                except Exception as e:
                    logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправке сообщения в Telegram чат.")
                    logger.debug("TRACEBACK", exc_info=True)
                    if isinstance(e, telebot.apihelper.ApiTelegramException) and e.result.status_code == 400 and \
                            "message thread not found" in str(e):
                        self.threads_pop(chat_id)
                        self.save_threads()
        if text:
            try:
                tag_text = tags if to_tag else ""
                self.current_bot.send_message(self.settings["chat_id"], text.rstrip() + tag_text,
                                              message_thread_id=thread_id, reply_markup=templates_kb(self),
                                              disable_notification=not self.settings["self_notify"] and only_self_messages)
                self.swap_curr_bot()
            except Exception as e:
                logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправке сообщения в Telegram чат.")
                logger.debug("TRACEBACK", exc_info=True)
                if isinstance(e, telebot.apihelper.ApiTelegramException) and e.result.status_code == 400 and \
                        "message thread not found" in str(e):
                    self.threads_pop(chat_id)
                    self.save_threads()

    def ingoing_message_handler(self, c: Cardinal, e: events.NewMessageEvent):
        if not self.ready:
            return
        if e.stack.id() == self.notification_last_stack_id:
            return
        self.notification_last_stack_id = e.stack.id()
        Thread(target=self.ingoing_message, args=(c, e), daemon=True).start()

    def new_order_handler(self, c: Cardinal, e: events.NewOrderEvent):
        if not self.ready or not self.tg.is_notification_enabled(self.settings["chat_id"], utils.NotificationTypes.new_order):
            return
        chat_id = c.account.get_chat_by_name(e.order.buyer_username).id
        if str(chat_id) not in self.threads:
            self.new_synced_chat(chat_id, e.order.buyer_username)

    # init message
    def sync_chat_on_start(self, c: Cardinal):
        chats = c.account.get_chats()
        self.sync_chats_running = True
        for i in chats:
            chat = chats[i]
            if str(i) in self.threads:
                continue
            self.new_synced_chat(chat.id, chat.name)
            time.sleep(BOT_DELAY / len(self.bots))
        self.sync_chats_running = False

    def sync_chat_on_start_handler(self, c: Cardinal, e: events.InitialChatEvent):
        if self.init_chat_synced or not self.ready:
            return
        self.init_chat_synced = True
        Thread(target=self.sync_chat_on_start, args=(c,), daemon=True).start()

    # TELEGRAM
    def no(self, c: telebot.types.CallbackQuery):
        self.tgbot.delete_message(c.message.chat.id, c.message.id)

    def check_bots(self):
        result = {}
        for i, bot in enumerate([self.tgbot, *self.bots]):
            is_main_bot = getattr(bot, "main_cs_bot", False)
            bot_id = None
            try:
                bot_id = self.bot_get_me(bot).id
            except:
                logger.warning(f"{LOGGER_PREFIX} Не удалось получить действие для {bot_id} ({i}).")
                logger.debug("TRACEBACK", exc_info=True)
            if not bot_id:
                continue
            elif not self.settings.get('chat_id'):
                result[bot_id] = "error"
            elif getattr(bot, "cs_is_ready", False) and not self.__recheck_bots:
                result[bot_id] = "ok"
            else:
                try:
                    member = self.tgbot.get_chat_member(self.settings["chat_id"], bot_id)
                    if member.status in ["left", "kicked"]:
                        result[bot_id] = "add"
                    elif member.status == "administrator" and (member.can_manage_topics or is_main_bot):
                        result[bot_id] = "ok"
                        setattr(bot, "cs_is_ready", True)
                    elif member.status != "administrator":
                        result[bot_id] = "admin"
                    else:
                        result[bot_id] = "rights"
                except Exception as e:
                    if isinstance(e, telebot.apihelper.ApiTelegramException) and "PARTICIPANT_ID_INVALID" in str(e):
                        result[bot_id] = "add"
                    else:
                        result[bot_id] = "error"
        self.__recheck_bots = False
        return result


    def open_settings_menu(self, c: telebot.types.CallbackQuery):
        """
        Основное меню настроек плагина.
        """
        split = c.data.split(":")
        uuid, offset = split[1], int(split[2])
        try:
            chat_name = self.tgbot.get_chat(self.settings["chat_id"])
            if not chat_name:
                chat_name = None
            elif chat_name.username:
                chat_name = f"@{chat_name.username}"
            elif chat_name.invite_link:
                chat_name = chat_name.invite_link
            else:
                chat_name = f"<code>{self.settings['chat_id']}</code>"
        except:
            chat_name = None

        problems = False
        instructions = "Все готово! Плагин работает, больше делать ничего не нужно :)"
        checked_bots = None
        if self.cardinal.old_mode_enabled:
            instructions = "Плагин не работает со старым режимом получения сообщений. Выключи его в /menu - Глобальные переключатели."
        elif len(self.bots) < MIN_BOTS:
            instructions = f"Сейчас тебе нужно создать {MIN_BOTS - len(self.bots)} бота(-ов) в @BotFather и добавить их токены в настройки плагина, нажав на кнопку \"<code>➕ Добавить Telegram бота</code>\".\n\n" \
                           f"⚠️ @username ботов должен начинаться с \"<code>funpay</code>\".\n\n" \
                           f'Для удобства аватарки ботов сделай одинаковыми.'
        elif not self.settings.get('chat_id'):
            instructions = f"Сейчас тебе нужно создать группу, перевести группу в режим тем. Для этого открой настройки группы и включи переключатель <code>Темы</code>.\n\n" \
                           f"Далее тебе нужно добавить в нее всех созданных ботов и основного (этого) бота.\n\n" \
                           f"Всех ботов ({len(self.bots) + 1} шт.) нужно назначить администраторами со всеми правами в этой группе.\n\n" \
                           f"После всего введи команду /setup_sync_chat в созданной группе и используй /sync_chats"
        elif set((checked_bots:=self.check_bots()).values()) != {"ok",}:
            instructions = f"Какие-то проблемы с некоторыми ботами... Реши их."
            problems = True
        elif not self.ready:
            instructions = f"Странно, вроде все правильно, но что-то не так... Попробуй перезапустить бота командой /restart :)"


        stats = f"""<b><i>Группа для FunPay чатов:</i></b> {chat_name or '<code>Не установлен.</code>'}\n
<b><i>Готов к работе:</i></b> <code>{"✅ Да." if self.ready and not problems else "❌ Нет."}</code>\n\n
<b><u>Что сейчас делать?</u></b>
{instructions}\n\n
<i>Обновлено:</i>  <code>{datetime.datetime.now().strftime('%H:%M:%S')}</code>"""
        self.tgbot.edit_message_text(stats, c.message.chat.id, c.message.id,
                                     reply_markup=plugin_settings_kb(self, offset, checked_bots), disable_web_page_preview=True)

    def open_switchers_menu(self, c: telebot.types.CallbackQuery):
        offset = int(c.data.split(":")[-1])
        self.tgbot.edit_message_text(_("pl_settings"), c.message.chat.id, c.message.id,
                                     reply_markup=switchers_kb(self, offset), disable_web_page_preview=True)

    def switch(self, c: telebot.types.CallbackQuery):
        __, setting, offset = c.data.split(":")
        self.settings[setting] = not self.settings[setting]
        self.save_settings()

        c.data = f"{CBT_SWITCHERS}:{offset}"
        self.open_switchers_menu(c)

    def act_add_sync_bot(self, c: telebot.types.CallbackQuery):
        split = c.data.split(":")
        offset = int(split[1])
        if len(self.bots) >= 10:
            self.tgbot.answer_callback_query(c.id, "❌ Достигнуто максимальное кол-во ботов.", show_alert=True)
            return
        result = self.tgbot.send_message(c.message.chat.id, "Отправь мне токен Telegram бота.",
                                         reply_markup=skb.CLEAR_STATE_BTN())
        self.tg.set_state(c.message.chat.id, result.id, c.from_user.id, ADD_SYNC_BOT, {"offset": offset})
        self.tgbot.answer_callback_query(c.id)

    def add_sync_bot(self, m: telebot.types.Message):
        offset = self.tg.get_state(m.chat.id, m.from_user.id)["data"]["offset"]
        self.tg.clear_state(m.chat.id, m.from_user.id, True)
        token = m.text
        if token in [i.token for i in self.bots]:
            self.tgbot.reply_to(m, "❌ Бот с таким токеном уже добавлен.", reply_markup=back_keyboard(offset))
            return
        if token == self.cardinal.telegram.bot.token:
            self.tgbot.reply_to(m, "❌ Основного бота сюда добавлять не нужно.", reply_markup=back_keyboard(offset))
            return
        bot = telebot.TeleBot(token, parse_mode="HTML", allow_sending_without_reply=True)
        try:
            data = self.bot_get_me(bot)
            username, bot_id = data.username, data.id
        except:
            logger.error(
                f"{LOGGER_PREFIX} Произошла ошибка при получении данных Telegram бота с токеном $YELLOW{token}$RESET.")
            logger.debug("TRACEBACK", exc_info=True)
            self.tgbot.reply_to(m, "❌ Произошла ошибка при получении данных о боте.",
                                reply_markup=back_keyboard(offset))
            return
        if not username.lower().startswith("funpay"):
            self.tgbot.reply_to(m, "❌ @username бота должен начинаться с \"<code>funpay</code>\".\n\n"
                                   f"@{username} не подходит.", reply_markup=back_keyboard(offset))
            return

        self.bots.append(bot)
        self.save_bots()
        if not self.current_bot:
            self.current_bot = self.bots[0]
        if not self.ready and len(self.bots) >= MIN_BOTS and self.settings.get(
                "chat_id") and not self.cardinal.old_mode_enabled:
            self.ready = True
        self.tgbot.reply_to(m, f"✅ Telegram бот @{username} добавлен!", reply_markup=back_keyboard(offset))
        return

    def delete_sync_bot(self, c: telebot.types.CallbackQuery):
        split = c.data.split(":")
        index, offset = int(split[1]), int(split[2])
        if len(self.bots) < index + 1:
            self.tgbot.edit_message_text(f"❌ Бот с индексом {index} не найден.", c.message.chat.id, c.message.id,
                                         reply_markup=back_keyboard(offset))
            self.tgbot.answer_callback_query(c.id)
            return

        self.bots.pop(index)
        self.current_bot = self.bots[0] if self.bots else None
        if not self.current_bot or len(self.bots) < MIN_BOTS or self.cardinal.old_mode_enabled:
            self.ready = False
        self.save_bots()
        c.data = f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"
        self.open_settings_menu(c)

    def bot_action(self, c: telebot.types.CallbackQuery):
        action = c.data.split(":")[-1]
        if action == "error":
            text = "Произошла ошибка при получении информации о правах бота."
        elif action == "ok":
            text = "С этим ботом всё хорошо."
        elif action == "rights":
            text = "У этого бота нет прав на создание тем в группе."
        elif action == "admin":
            text = "Бот не является администратором в группе."
        else:
            text = "Не пон. Где ты нашел эту кнопку?"
        self.tgbot.answer_callback_query(c.id, text, show_alert=True)

    def setup_sync_chat(self, m: telebot.types.Message):
        if m.from_user.id == m.chat.id:
            self.tgbot.reply_to(m,
                                "❌ Эту команду нужно вводить в созданной группе!")
            return
        if not m.chat.is_forum:
            self.tgbot.reply_to(m,
                                "❌ Чат должен быть перевед в режим тем! Полный гайд по установке находится в настройках данного плагина.")
            return
        if self.settings.get("chat_id"):
            self.tgbot.reply_to(m, "Ты уверен, что хочешь изменить группу для синхронизации Funpay чатов?\n\n"
                                   "Пары <code>Telegram топик - FunPay чат</code> сбросятся!",
                                reply_markup=setup_chat_keyboard())
            return
        self.settings["chat_id"] = m.chat.id
        self.save_settings()
        self.threads = {}
        self.__reversed_threads = {}
        self.save_threads()
        if not self.ready and self.current_bot and len(self.bots) >= MIN_BOTS and not self.cardinal.old_mode_enabled:
            self.ready = True
        self.tgbot.send_message(m.chat.id, "✅ Группа для синхронизации FunPay чатов установлена!")

    def confirm_setup_sync_chat(self, c: telebot.types.CallbackQuery):
        if not c.message.chat.is_forum:
            self.tgbot.edit_message_text("❌ Чат должен быть перевед в режим тем!",
                                         c.message.chat.id, c.message.id)
            self.tgbot.answer_callback_query(c.id)
            return
        self.settings["chat_id"] = c.message.chat.id
        self.save_settings()
        self.threads = {}
        self.__reversed_threads = {}
        self.__recheck_bots = True
        self.save_threads()
        if not self.ready and self.current_bot and len(self.bots) >= MIN_BOTS and not self.cardinal.old_mode_enabled:
            self.ready = True
        self.tgbot.edit_message_text("✅ Группа для синхронизации FunPay чатов установлена!",
                                     c.message.chat.id, c.message.id)

    def delete_sync_chat(self, m: telebot.types.Message):
        if not self.settings.get('chat_id'):
            self.tgbot.reply_to(m, "❌ Группа для синхронизации FunPay чатов итак не привязана!")
            return
        self.tgbot.reply_to(m, "Ты уверен, что хочешь отвязать группу для синхронизации FunPay чатов?\n\n"
                               "Пары <code>Telegram топик - FunPay чат</code> сбросятся!",
                            reply_markup=delete_chat_keyboard())

    def confirm_delete_sync_chat(self, c: telebot.types.CallbackQuery):
        self.settings["chat_id"] = None
        self.save_settings()
        self.threads = {}
        self.__reversed_threads = {}
        self.__recheck_bots = True
        self.save_threads()
        self.ready = False
        self.tgbot.edit_message_text("✅ Группа для синхронизации FunPay чатов отвязана.",
                                     c.message.chat.id, c.message.id)

    def sync_chats(self, m: telebot.types.Message):
        if not self.current_bot:
            return
        if self.sync_chats_running:
            self.tgbot.reply_to(m,
                                "❌ Синхронизация чатов уже запущена! Дождитесь окончания процесса или перезапустите <i>FPC</i>.")
            return

        self.sync_chats_running = True
        chats = self.cardinal.account.get_chats(update=True)
        for chat in chats:
            obj = chats[chat]
            if str(chat) not in self.threads:
                self.new_synced_chat(obj.id, obj.name)
            time.sleep(BOT_DELAY / len(self.bots))
        self.sync_chats_running = False

    def send_message(self, m: telebot.types.Message):
        if m.reply_to_message and m.reply_to_message.forum_topic_created:
            username, chat_id = m.reply_to_message.forum_topic_created.name.split()
            username = username.split("👤")[-1]
            chat_id = int(chat_id.replace("(", "").replace(")", ""))
        else:
            chat_id = self.__reversed_threads.get(m.message_thread_id)
            chat = self.cardinal.account.get_chat_by_id(int(chat_id))
            if chat:
                username = chat.name
            else:
                username = None

        result = self.cardinal.send_message(chat_id, f"{SPECIAL_SYMBOL}{m.text}", username, watermark=False)
        if not result:
            self.current_bot.reply_to(m, _("msg_sending_error", chat_id, username),
                                      message_thread_id=m.message_thread_id)
            self.swap_curr_bot()

    def send_template(self, m: telebot.types.Message):
        n, result = m.text.lstrip(SPECIAL_SYMBOL).split(f"){SPECIAL_SYMBOL} ", maxsplit=1)
        n = int(n) - 1
        if len(self.cardinal.telegram.answer_templates) > n \
                and self.cardinal.telegram.answer_templates[n].startswith(result.rstrip("…")):
            m.text = self.cardinal.telegram.answer_templates[n]
        elif not result.endswith("…"):
            m.text = result
        else:
            self.current_bot.reply_to(m, f"❌ Шаблон {n + 1} не найден.", message_thread_id=m.message_thread_id,
                                      reply_markup=templates_kb(self))
            self.swap_curr_bot()
            return

        self.send_message(m)

    def send_message_error(self, m: telebot.types.Message):
        self.current_bot.reply_to(m, "❌ Не используй реплай!", message_thread_id=m.message_thread_id)
        self.swap_curr_bot()

    def watch(self, m: telebot.types.Message):
        if not m.chat.id == self.settings.get(
                "chat_id") or not m.reply_to_message or not m.reply_to_message.forum_topic_created:
            self.tgbot.reply_to(m, "❌ Данную команду необходимо вводить в одном из синк-чатов!")
            return
        tg_chat_name = m.reply_to_message.forum_topic_created.name
        username, chat_id = tg_chat_name.split()
        username = username.split("👤")[-1]
        chat_id = int(chat_id.replace("(", "").replace(")", ""))
        try:
            chat = self.cardinal.account.get_chat(chat_id, with_history=False)
            looking_text = chat.looking_text
            looking_link = chat.looking_link
        except:
            logger.error(
                f"{LOGGER_PREFIX} Произошла ошибка при получении данных чата $YELLOW{username} (CID: {chat_id})$RESET.")
            logger.debug("TRACEBACK", exc_info=True)
            self.current_bot.reply_to(m,
                                      f"❌ Произошла ошибка при получении данных чата с <a href=\"https://funpay.com/chat/?node={chat_id}\">{username}</a>")
            self.swap_curr_bot()
            return

        if looking_text and looking_link:
            text = f"<b><i>Смотрит: </i></b> <a href=\"{looking_link}\">{utils.escape(looking_text)}</a>"
        else:
            text = f"<b>Пользователь <code>{username}</code> ничего не смотрит.</b>"
        self.current_bot.reply_to(m, text)
        self.swap_curr_bot()

    def watch_handler(self, m: telebot.types.Message):
        Thread(target=self.watch, args=(m,)).start()

    def history(self, m: telebot.types.Message):
        if not m.chat.id == self.settings.get(
                "chat_id") or not m.reply_to_message or not m.reply_to_message.forum_topic_created:
            self.tgbot.reply_to(m, "❌ Данную команду необходимо вводить в одном из синк-чатов!")
            return
        tg_chat_name = m.reply_to_message.forum_topic_created.name
        username, chat_id = tg_chat_name.split()
        username = username.split("👤")[-1]
        chat_id = int(chat_id.replace("(", "").replace(")", ""))
        try:
            history = self.cardinal.account.get_chat_history(chat_id, interlocutor_username=username)
            if not history:
                self.tgbot.reply_to(m,
                                    f"❌ История чата с <a href=\"https://funpay.com/chat/?node={chat_id}\">{username}</a> пуста.")
                return
            history = history[-25:]
            messages = self.create_chat_history_messages(history)
        except:
            logger.error(
                f"{LOGGER_PREFIX} Произошла ошибка при получении истории чата $YELLOW{username} (CID: {chat_id})$RESET.")
            logger.debug("TRACEBACK", exc_info=True)
            self.tgbot.reply_to(m,
                                f"❌ Произошла ошибка при получении истории чата с <a href=\"https://funpay.com/chat/?node={chat_id}\">{username}</a>")
            self.swap_curr_bot()
            return

        for i in messages:
            try:
                self.current_bot.send_message(m.chat.id, i, message_thread_id=m.message_thread_id)
                self.swap_curr_bot()
            except:
                logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправки сообщения в Telegram топик.")
                logger.debug("TRACEBACK", exc_info=True)

    def history_handler(self, m: telebot.types.Message):
        Thread(target=self.history, args=(m,)).start()

    def send_funpay_image(self, m: telebot.types.Message):

        if not self.settings["chat_id"] or m.chat.id != self.settings["chat_id"] or \
                not m.reply_to_message or not m.reply_to_message.forum_topic_created:
            return

        tg_chat_name = m.reply_to_message.forum_topic_created.name
        username, chat_id = tg_chat_name.split()
        username = username.split("👤")[-1]
        chat_id = int(chat_id.replace("(", "").replace(")", ""))
        if chat_id not in self.photos_mess:
            self.photos_mess[chat_id] = [m, ]
        else:
            self.photos_mess[chat_id].append(m)
            return
        while self.photos_mess[chat_id]:
            self.photos_mess[chat_id].sort(key=lambda x: x.id)
            m = self.photos_mess[chat_id].pop(0)
            try:
                if m.caption is not None:
                    m.text = m.caption
                    self.send_message(m)
                photo = m.photo[-1] if m.photo else m.document
                if photo.file_size >= 20971520:
                    self.tgbot.reply_to(m, "❌ Размер файла не должен превышать 20МБ.")
                    return
                file_info = self.tgbot.get_file(photo.file_id)
                file = self.tgbot.download_file(file_info.file_path)
                if file_info.file_path.endswith(".webp"):
                    webp_image = Image.open(io.BytesIO(file))
                    rgb_image = Image.new("RGB", webp_image.size, (255, 255, 255))
                    rgb_image.paste(webp_image, (0, 0), mask=webp_image.convert("RGBA").split()[3])
                    output_buffer = io.BytesIO()
                    rgb_image.save(output_buffer, format='JPEG')
                    file = output_buffer.getvalue()
                result = self.cardinal.account.send_image(chat_id, file, username, True,
                                                          update_last_saved_message=self.cardinal.old_mode_enabled)
                if not result:
                    self.current_bot.reply_to(m, _("msg_sending_error", chat_id, username),
                                              message_thread_id=m.message_thread_id)
                    self.swap_curr_bot()
            except (ImageUploadError, MessageNotDeliveredError) as ex:
                logger.error(f"{LOGGER_PREFIX} {ex.short_str()}")
                logger.debug("TRACEBACK", exc_info=True)
                msg = ex.error_message if ex.error_message else ""
                self.current_bot.reply_to(m, f'{_("msg_sending_error", chat_id, username)} {msg}',
                                          message_thread_id=m.message_thread_id)
                self.swap_curr_bot()
            except Exception as ex:
                logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправке изображения.")
                logger.debug("TRACEBACK", exc_info=True)
                self.current_bot.reply_to(m, _("msg_sending_error", chat_id, username),
                                          message_thread_id=m.message_thread_id)
                self.swap_curr_bot()
        del self.photos_mess[chat_id]

    def send_funpay_sticker(self, m: telebot.types.Message):
        sticker = m.sticker
        m.photo = [sticker]
        m.caption = None
        self.send_funpay_image(m)

    # full history
    def get_full_chat_history(self, chat_id: int, interlocutor_username: str) -> list[FunPayAPI.types.Message]:
        total_history = []
        last_message_id = 999999999999999999999999999999999999999999999999999999999

        while True:
            history = self.cardinal.account.get_chat_history(chat_id, last_message_id, interlocutor_username)
            if not history:
                break
            temp_last_message_id = history[0].id
            if temp_last_message_id == last_message_id:
                break
            last_message_id = temp_last_message_id
            total_history = history + total_history
            time.sleep(0.2)
        return total_history

    def create_chat_history_messages(self, messages: list[FunPayAPI.types.Message]) -> list[str]:
        result = []
        while messages:
            text = ""
            last_message_author_id = -1
            last_by_bot = False
            last_badge = None
            last_by_vertex = False
            while messages:
                i = messages[0]
                message_text = str(i)
                if i.author_id == last_message_author_id and i.by_bot == last_by_bot and i.badge == last_badge and \
                        last_by_vertex == i.by_vertex:
                    author = ""
                elif i.author_id == self.cardinal.account.id:
                    author = f"<i><b>🤖 {_('you')} (<i>FPC</i>):</b></i> " if i.by_bot else f"<i><b>🫵 {_('you')}:</b></i> "
                    if i.is_autoreply:
                        author = f"<i><b>📦 {_('you')} ({i.badge}):</b></i> "
                elif i.author_id == 0:
                    author = f"<i><b>🔵 {i.author}: </b></i>"
                elif i.is_employee:
                    author = f"<i><b>🆘 {i.author} ({i.badge}): </b></i>"
                elif i.author == i.chat_name:
                    author = f"<i><b>👤 {i.author}: </b></i>"
                    if i.is_autoreply:
                        author = f"<i><b>🛍️ {i.author} ({i.badge}):</b></i> "
                    elif i.author in self.cardinal.blacklist:
                        author = f"<i><b>🚷 {i.author}: </b></i>"
                    elif i.by_bot:
                        author = f"<i><b>🐦 {i.author}: </b></i>"
                    elif i.by_vertex:
                        author = f"<i><b>🐺 {i.author}: </b></i>"
                else:
                    author = f"<i><b>🆘 {i.author} {_('support')}: </b></i>"

                if not i.text:
                    msg_text = f"<a href=\"{message_text}\">" \
                               f"{self.settings.get('image_name') and not (i.author_id == self.cardinal.account.id and i.by_bot) and i.image_name or _('photo')}</a>"

                elif i.author_id == 0:
                    msg_text = f"<b><i>{utils.escape(message_text)}</i></b>"
                else:
                    msg_text = utils.escape(message_text)

                last_message_author_id = i.author_id
                last_by_bot = i.by_bot
                last_badge = i.badge
                last_by_vertex = i.by_vertex
                res_str = f"{author}{msg_text}\n\n"
                if len(text) + len(res_str) <= 4096:
                    text += res_str
                    del messages[0]
                else:
                    break
            result.append(text.strip())

        return result

    def full_history(self, m: telebot.types.Message):
        if not m.chat.id == self.settings.get(
                "chat_id") or not m.reply_to_message or not m.reply_to_message.forum_topic_created:
            self.tgbot.reply_to(m, "❌ Данную команду необходимо вводить в одном из синк-чатов!")
            return

        if self.full_history_running:
            self.tgbot.reply_to(m,
                                "❌ Получение истории чата уже запущено! Дождитесь окончания процесса или перезапустите <i>FPC</i>.")
            return

        self.full_history_running = True
        tg_chat_name = m.reply_to_message.forum_topic_created.name
        username, chat_id = tg_chat_name.split()
        username = username.split("👤")[-1]
        chat_id = int(chat_id.replace("(", "").replace(")", ""))

        self.tgbot.reply_to(m,
                            f"Начинаю изучение истории чата <a href=\"https://funpay.com/chat/?node={chat_id}\">{username}</a>...\nЭто может занять некоторое время.")
        try:
            history = self.get_full_chat_history(chat_id, username)
            messages = self.create_chat_history_messages(history)
        except:
            self.full_history_running = False
            self.tgbot.reply_to(m,
                                f"❌ Произошла ошибка при получении истории чата <a href=\"https://funpay.com/chat/?node={chat_id}\">{username}</a>.")
            logger.debug("TRACEBACK", exc_info=True)
            return

        for i in messages:
            try:
                self.current_bot.send_message(m.chat.id, i, message_thread_id=m.message_thread_id)
                self.swap_curr_bot()
            except:
                logger.error(f"{LOGGER_PREFIX} Произошла ошибка при отправки сообщения в Telegram топик.")
                logger.debug("TRACEBACK", exc_info=True)
            time.sleep(BOT_DELAY / len(self.bots))

        self.full_history_running = False
        self.tgbot.reply_to(m, f"✅ Готово!")

    def full_history_handler(self, m: telebot.types.Message):
        Thread(target=self.full_history, args=(m,)).start()

    def templates_handler(self, m: telebot.types.Message):
        if not m.chat.id == self.settings.get(
                "chat_id") or not m.reply_to_message or not m.reply_to_message.forum_topic_created:
            self.tgbot.reply_to(m, "❌ Данную команду необходимо вводить в одном из синк-чатов!")
            return
        tg_chat_name = m.reply_to_message.forum_topic_created.name
        username, chat_id = tg_chat_name.split()
        username = username.split("👤")[-1]
        chat_id = int(chat_id.replace("(", "").replace(")", ""))
        self.tgbot.send_message(m.chat.id, _("msg_templates"),
                                reply_markup=keyboards.templates_list_ans_mode(self.cardinal, 0, chat_id, username, 3),
                                message_thread_id=m.message_thread_id)


cs_obj = None


def main(c: Cardinal):
    cs = ChatSync(c)
    global cs_obj
    cs_obj = cs
    cs.load()
    cs.replace_handler()
    cs.bind_tg_handlers()

    def new_send_notification(self, text: str | None, keyboard: K | None = None,
                              notification_type: str = utils.NotificationTypes.other, photo: bytes | None = None,
                              pin: bool = False):
        """
        Отправляет сообщение во все чаты для уведомлений из self.notification_settings.

        :param text: текст уведомления.
        :param keyboard: экземпляр клавиатуры.
        :param notification_type: тип уведомления.
        :param photo: фотография (если нужна).
        :param pin: закреплять ли сообщение.
        """
        kwargs = {}
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard
        to_delete = []
        for chat_id in self.notification_settings:
            if notification_type != utils.NotificationTypes.important_announcement and \
                    not self.is_notification_enabled(chat_id, notification_type):
                continue

            def get_fp_chat_id(keyboard: K):
                for row in keyboard.to_dict()["inline_keyboard"]:
                    for button in row:
                        if button["text"] == _("ord_answer"):
                            return button["callback_data"].split(":")[1]
                return 0

            message_thread_id = None
            if chat_id == str(cs.settings["chat_id"]) and keyboard is not None:
                if fp_chat_id := get_fp_chat_id(keyboard):
                    message_thread_id = cs.threads.get(fp_chat_id)
            try:
                if photo:
                    msg = self.bot.send_photo(chat_id, photo, text, **kwargs, message_thread_id=message_thread_id)
                else:
                    msg = self.bot.send_message(chat_id, text, **kwargs, message_thread_id=message_thread_id)

                if notification_type == utils.NotificationTypes.bot_start:
                    self.init_messages.append((msg.chat.id, msg.id))

                if pin:
                    self.bot.pin_chat_message(msg.chat.id, msg.id)
            except Exception as e:
                logger.error(_("log_tg_notification_error", chat_id))
                logger.debug("TRACEBACK", exc_info=True)
                if isinstance(e, ApiTelegramException) and (
                        e.result.status_code == 403 or e.result.status_code == 400 and
                        (e.result_json.get('description') in \
                         ("Bad Request: group chat was upgraded to a supergroup chat", "Bad Request: chat not found"))):
                    to_delete.append(chat_id)
                continue
        for chat_id in to_delete:
            if chat_id in self.notification_settings:
                del self.notification_settings[chat_id]
                utils.save_notification_settings(self.notification_settings)

    global tg_bot
    tg_bot.bot.TGBot.send_notification = new_send_notification


def new_act_send_funpay_message(self, c: CallbackQuery):
    """
    Активирует режим ввода сообщения для отправки его в чат FunPay.
    """
    logger.debug(f"{LOGGER_PREFIX} Поведение функции act_send_funpay_message подменено плагином.")
    split = c.data.split(":")
    node_id = int(split[1])
    try:
        username = split[2]
    except IndexError:
        username = None
    if cs_obj is not None and (cs_obj.is_outgoing_message(c.message) or cs_obj.is_error_message(c.message)):
        self.bot.answer_callback_query(c.id, text=_("gl_no"), show_alert=True)
        return
    result = self.bot.send_message(c.message.chat.id, _("enter_msg_text"), reply_markup=skb.CLEAR_STATE_BTN())
    self.set_state(c.message.chat.id, result.id, c.from_user.id,
                   CBT.SEND_FP_MESSAGE, {"node_id": node_id, "username": username})
    self.bot.answer_callback_query(c.id)


tg_bot.bot.TGBot.act_send_funpay_message = new_act_send_funpay_message

BIND_TO_PRE_INIT = [main]
BIND_TO_DELETE = None
