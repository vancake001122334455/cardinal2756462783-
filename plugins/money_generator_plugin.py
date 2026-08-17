from __future__ import annotations

import os
import random
import string
from typing import TYPE_CHECKING, IO
import requests
from requests_toolbelt import MultipartEncoder
from PIL import Image
from io import BytesIO
from FunPayAPI.common import exceptions
from FunPayAPI.types import LotShortcut
from announcements import download_photo
from tg_bot import CBT
from tg_bot.utils import escape

if TYPE_CHECKING:
    from cardinal import Cardinal

if TYPE_CHECKING:
    from cardinal import Cardinal
import telebot
from logging import getLogger
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import time

NAME = "Money Generator Plugin"
VERSION = "0.0.1"
DESCRIPTION = "Плагин для генерации денег."

CREDITS = "@sidor0912"
UUID = "4b74617f-e261-4fd9-8ee3-7c4600ea52d9"
SETTINGS_PAGE = True

logger = getLogger("FPC.money_generator_plugin")
LOGGER_PREFIX = "[MONEY_GENERATOR]"
PLUGIN_FOLDER = f"storage/plugins/money_generator"
CBT_MONEY_GENERATE = "MoneyGenerator.start"
CBT_STOP = "MoneyGenerator.stop"
CBT_BECOME_POOR = "MoneyGenerator.become_poor"

class MoneyGenerator:
    def __init__(self, crd: Cardinal):
        if hasattr(self, "initialized"):
            return
        self.initialized = True
        self.cardinal = crd
        self.tg = None
        self.tgbot = None
        if self.cardinal.telegram:
            self.tg = self.cardinal.telegram
            self.tgbot = self.tg.bot
        self.stop = False
        self.profile_photo = None
        self.money_photo = None
        self.result_photo = None
        self.i_am_rich_time = 0
        self.attempts = 0
        self.was_rich = False
        self.lot: None | LotShortcut = None

    def upload_image(self, image: str | IO[bytes]) -> int:
        account = self.cardinal.account
        if not account.is_initiated:
            raise exceptions.AccountNotInitiatedError()

        if isinstance(image, str):
            with open(image, "rb") as f:
                img = f.read()
        else:
            img = image

        fields = {
            'file': ("Отправлено_с_помощью_бота_FunPay_Cardinal.png", img, "image/png"),
            'file_id': "0"
        }
        boundary = '----WebKitFormBoundary' + ''.join(random.sample(string.ascii_letters + string.digits, 16))
        m = MultipartEncoder(fields=fields, boundary=boundary)

        headers = {
            "accept": "*/*",
            "x-requested-with": "XMLHttpRequest",
            "content-type": m.content_type,
        }
        response = account.method("post", f"https://funpay.com/file/avatar", headers, m)
        if response.status_code == 400:
            try:
                json_response = response.json()
                message = json_response.get("msg")
                raise exceptions.ImageUploadError(response, message)
            except requests.exceptions.JSONDecodeError:
                raise exceptions.ImageUploadError(response, None)
        elif response.status_code != 200:
            raise exceptions.RequestFailedError(response)
        logger.info(f"{LOGGER_PREFIX} Деньги сгенерированы.")


    def open_settings(self, call: telebot.types.CallbackQuery):
        kb = K()
        offset = call.data.split(":")[-1]
        if self.i_am_rich_time:
            kb.add(B("📉 Снова стать бедным", callback_data=f"{CBT_BECOME_POOR}:{offset}"))
        else:
            kb.add(B("📈 Сгенерировать деньги", callback_data=f"{CBT_MONEY_GENERATE}:{offset}"))
        kb.add(B("◀️ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:{offset}"))
        self.tgbot.edit_message_text("В данном разделе Вы можете сгенерировать деньги.",
                              call.message.chat.id, call.message.id, reply_markup=kb)

    def stop_generation_click(self, call: telebot.types.CallbackQuery):
        offset = call.data.split(":")[-1]
        self.stop = True
        call.data = f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"
        self.open_settings(call)

    def generate(self):
        base = Image.open(BytesIO(self.profile_photo)).convert("RGBA")
        money = Image.open(BytesIO(self.money_photo)).convert("RGBA")
        money = money.resize(base.size)
        result = Image.alpha_composite(base, money)

        output_bytes = BytesIO()
        result.save(output_bytes, format="PNG")
        return output_bytes

    def become_poor_click(self, call: telebot.types.CallbackQuery):
        offset = call.data.split(":")[-1]
        if not self.i_am_rich_time:
            self.tgbot.answer_callback_query(call.id, "Вы и так бедны. Куда ещё беднее?", show_alert=True)
            call.data = f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"
            self.open_settings(call)
            return
        t = int((30 * 60 - (time.time() - self.i_am_rich_time))//60)
        if t > 0 and self.attempts < 10:
            self.tgbot.answer_callback_query(call.id, f"Ещё рано... Насладитесь богатством ещё {t} мин.", show_alert=True)
            self.attempts += 1
            return
        self.upload_image(f"{PLUGIN_FOLDER}/photo.png")
        self.i_am_rich_time = 0
        self.attempts = 0
        self.tgbot.answer_callback_query(call.id, f"Поздравляем! Вы снова бедны.", show_alert=True)

        call.data = f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"
        self.open_settings(call)

    def progress_bar(self, percent: int, length: int = 20) -> str:
        filled = int(length * percent / 100)
        return "█" * filled + "░" * (length - filled)

    def get_stages(self, i: int) -> list[str]:
        category = f" категории <u>{escape(self.lot.subcategory.ui_name)}</u>" if self.lot else ""
        lot_name = f"у <u>{escape(self.lot.description)}</>" if self.lot and self.lot.description else "ы"
        result = [
            f"🔐 Подключаемся к {self.cardinal.account.username} ({self.cardinal.account.id})",
            "👤 Cardinal входит в аккаунт (делает вид, что это не он)",
            "📡 Пингуем FunPay API... API делает вид, что нас не знает",
            f"🧾 Открываем лоты{category} и притворяемся аналитиками",
            "📊 Считаем конкурентов... их слишком много 🤯",
            f"💰 Поднимаем цен{lot_name} на 1% и чувствуем себя бизнесменом",
            "🤝 Обрабатываем заказ #VYJW1HZD... надеемся, что не фейк",
            "📦 Собираем виртуальный товар в виртуальную коробку...",
            "💸 Конвертируем пиксели в деньги...",
            "🧾 Сводим бухгалтерию, чтобы налоговая не задавала лишних вопросов...",
            "✅ Процесс завершен. Проверьте аккаунт FunPay на наличие сгенерированных денег."
        ][:i+1]
        result = result[-5:]
        if len(result) < 5:
            result.extend(["" for _ in range(5-len(result))])
        return result

    def money_generate_click(self, call: telebot.types.CallbackQuery):
        offset = call.data.split(":")[-1]
        if self.i_am_rich_time:
            self.tgbot.answer_callback_query(call.id, "Вы и так богаты. Деньги Вам ни к чему.", show_alert=True)
            return
        if self.was_rich and self.i_am_rich_time == 0:
            self.tgbot.answer_callback_query(call.id, "Вы уже были богатым и отказались от своего богатства.", show_alert=True)
            return
        if not os.path.exists(PLUGIN_FOLDER):
            os.makedirs(PLUGIN_FOLDER)
        self.stop = False
        steps = 10
        try:
            for i in range(0, steps + 1):
                percent = i * 10
                text = "⏳ Генерация денег..."
                kb = K().add(
                    B("🛑 Остановить генерацию денег", callback_data=f"{CBT_STOP}:{offset}")
                )
                if i == 0:
                    lots = self.cardinal.profile.get_lots()
                    if lots and not self.lot:
                        self.lot = random.choice(lots)

                elif i == 6:
                    if not self.profile_photo:
                        self.profile_photo = download_photo(self.cardinal.profile.profile_photo)

                elif i == 7:
                    if not os.path.exists(f"{PLUGIN_FOLDER}/photo.png"):
                        if not self.profile_photo:
                            raise Exception()
                        with open(f"{PLUGIN_FOLDER}/photo.png", "wb") as f:
                            f.write(self.profile_photo)

                elif i == 8:
                    if not self.money_photo:
                        self.money_photo = download_photo(
                            "https://www.freeiconspng.com/uploads/dollar-flying-money-png-4.png")

                elif i == 9:
                    if not self.money_photo:
                        raise Exception()
                    if not self.result_photo:
                        self.result_photo = self.generate()

                elif i == 10:
                    if self.stop:
                        return
                    if not self.result_photo:
                        raise Exception()

                    self.upload_image(self.result_photo)

                    text = "💸 Генерация денег завершена."
                    kb = (K().add(B("🔍 Проверить", url=f"https://funpay.com/users/{self.cardinal.account.id}/"))
                          .add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}")))
                    self.i_am_rich_time = time.time()
                    self.was_rich = True

                if self.stop:
                    return

                bar = self.progress_bar(percent)
                quote = "<blockquote>" + "\n".join(self.get_stages(i)) + f"\n\n[{bar}] {percent}%" + "</blockquote>"
                text = (
                    f"<b>{text}</b>\n\n{quote}\n"
                )

                try:
                    self.tgbot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.id,
                        reply_markup=kb
                    )
                except Exception:
                    logger.warning(f"{LOGGER_PREFIX} Возникла ошибка изменении сообщения.")
                    logger.debug("TRACEBACK", exc_info=True)

                time.sleep(1.5 + i * 1.5)
        except:
            logger.warning(f"{LOGGER_PREFIX} Возникла ошибка генерации денег.")
            logger.debug("TRACEBACK", exc_info=True)
            if self.stop:
                return
            self.tgbot.edit_message_text(f"😭 Возникла ошибка при генерации денег(", call.message.chat.id, call.message.id,
                                         reply_markup=K().add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}")))


    def reg_tg_handlers(self):
        self.tg.cbq_handler(self.open_settings, lambda c: f"{CBT.PLUGIN_SETTINGS}:{UUID}" in c.data)
        self.tg.cbq_handler(self.money_generate_click, lambda c: c.data.startswith(f"{CBT_MONEY_GENERATE}:"))
        self.tg.cbq_handler(self.become_poor_click, lambda c: c.data.startswith(f"{CBT_BECOME_POOR}:"))
        self.tg.cbq_handler(self.stop_generation_click, lambda c: f"{CBT_STOP}" in c.data)


def init(crd: Cardinal, *args):
    mg = MoneyGenerator(crd)
    mg.reg_tg_handlers()


BIND_TO_PRE_INIT = [init]
BIND_TO_DELETE = None
