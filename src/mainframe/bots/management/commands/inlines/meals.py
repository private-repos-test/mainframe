import logging
import math

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from mainframe.bots.management.commands.inlines.shared import BaseInlines, chunks
from mainframe.clients.chat import edit_message
from mainframe.clients.meals import MealsClient
from mainframe.meals.models import Meal

logger = logging.getLogger(__name__)


def parse_meal(item: Meal):
    ingredients = "\n".join(
        [f"{i + 1}. {ingredient}" for i, ingredient in enumerate(item.ingredients)]
    )
    quantities = "\n".join([f"{k} - {v}" for k, v in item.quantities.items()])
    return f"""
<b>{item.name}</b>
{item.date.isoformat()}, {item.get_type_display()}

{item.name or "-"}

Ingredients:
{ingredients}

Quantity:
{quantities}
"""


class MealsInline(BaseInlines):
    PER_PAGE = 24

    @classmethod
    async def get_meals_markup(cls, day, page, bottom_level=False):
        buttons = [[InlineKeyboardButton("✅", callback_data="end")]]
        if bottom_level:
            buttons[0].insert(
                0,
                InlineKeyboardButton(
                    "👆", callback_data=f"meals fetch_day {day} {page}"
                ),
            )
            return InlineKeyboardMarkup(buttons)

        buttons[0].insert(
            0, InlineKeyboardButton("👆", callback_data=f"meals start {page}")
        )

        @sync_to_async
        def fetch_meals():
            return list(Meal.objects.filter(date=day).order_by("type"))

        items = await fetch_meals()
        logger.info("Got %d meals", len(items))

        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{item.get_type_display()}",
                        callback_data=f"meals fetch {item.pk} {page}",
                    )
                ]
                for item in items
            ]
            + buttons
        )

    @classmethod
    async def get_markup(cls, page=1, is_top_level=False, last_page=None):
        buttons = [
            [
                InlineKeyboardButton("✅", callback_data="end"),
                InlineKeyboardButton("♻️", callback_data="meals sync"),
            ]
        ]

        if not is_top_level:
            buttons[0].insert(
                0,
                InlineKeyboardButton("👆", callback_data=f"meals start {page}"),
            )
            return InlineKeyboardMarkup(buttons)

        if last_page != 1:
            buttons[0].insert(
                0,
                InlineKeyboardButton(
                    "👈",
                    callback_data=f"meals start {page - 1 if page > 1 else last_page}",
                ),
            )
            buttons[0].append(
                InlineKeyboardButton(
                    "👉",
                    callback_data=f"meals start {page + 1 if page != last_page else 1}",
                )
            )

        start = (page - 1) * cls.PER_PAGE if page - 1 >= 0 else 0

        @sync_to_async
        def fetch_meals():
            return list(
                Meal.objects.distinct("date").order_by("date", "type")[
                    start : start + cls.PER_PAGE
                ]
            )

        items = await fetch_meals()
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{item.date.strftime('%d %b %y')}",
                        callback_data=(
                            f"meals fetch_day {item.date.strftime('%Y-%m-%d')} {page}"
                        ),
                    )
                    for item in chunk
                ]
                for chunk in chunks(items, 3)
            ]
            + buttons
        )

    @classmethod
    async def fetch_day(cls, update, day, page):
        message = update.callback_query.message

        return await edit_message(
            update.callback_query._bot,
            message.chat.id,
            message.message_id,
            text=day,
            reply_markup=await cls.get_meals_markup(day=day, page=page),
        )

    @classmethod
    async def fetch(cls, update, _id, page):
        message = update.callback_query.message

        @sync_to_async
        def fetch_item():
            try:
                return Meal.objects.get(pk=_id)
            except Meal.DoesNotExist:
                pass

        item = await fetch_item()

        return await edit_message(
            bot=update.callback_query._bot,
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=parse_meal(item) if item else "Not found",
            reply_markup=await cls.get_meals_markup(
                day=item.date.strftime("%Y-%m-%d"), page=page, bottom_level=True
            ),
        )

    @classmethod
    async def start(cls, update, page=None, override_message=None, **__):
        @sync_to_async
        def fetch_count():
            return Meal.objects.distinct("date").count()

        count = await fetch_count()
        logger.info("Counted %s dates", count)
        last_page = math.ceil(count / cls.PER_PAGE)
        welcome_message = "Welcome {name}\nChoose a date [{page} / {total}]"

        if not update.callback_query:
            user = update.message.from_user
            logger.info("User %s started the conversation.", user.full_name)

            return update.message.reply_text(
                (
                    override_message
                    if override_message
                    else welcome_message.format(
                        name=user.full_name, page=1, total=last_page
                    )
                ),
                reply_markup=await cls.get_markup(
                    is_top_level=True, last_page=last_page
                ),
            )

        message = update.callback_query.message
        user = update.callback_query.from_user
        return await edit_message(
            bot=update.callback_query._bot,
            chat_id=message.chat.id,
            message_id=message.message_id,
            text=(
                override_message
                if override_message
                else welcome_message.format(
                    name=user.full_name, page=page or 1, total=last_page
                )
            ),
            reply_markup=await cls.get_markup(
                page=int(page) if page else 1,
                is_top_level=True,
                last_page=last_page,
            ),
        )

    @classmethod
    async def sync(cls, update):
        @sync_to_async
        def fetch_meals():
            return MealsClient.fetch_meals()

        meals = await fetch_meals()
        override_message = f"Fetched {len(meals)} meals 👌"
        return await cls.start(update, override_message=override_message)
