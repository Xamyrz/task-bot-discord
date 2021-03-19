import asyncio
import datetime
import logging
import time
from asyncio import get_running_loop
from time import strftime

import discord
import pytz
from bson import ObjectId
from discord.ext import tasks, commands
from motor.motor_asyncio import AsyncIOMotorClient

from commands.task import Task, AZ_EMOJIS
from essentials.multi_server import ask_for_server
from essentials.settings import SETTINGS


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ignore_next_removed_reaction = {}
        self.index = 0
        self.user_auto_notifications.add_exception_type(KeyError)
        self.user_auto_notifications.start()
        get_running_loop().create_task(self.startup_notifications())

    async def notify_user(self, td, notify, utc_now):
        # load task and update DB
        t = Task(self.bot, load=True)
        await t.task_from_dict(td)
        if notify == 7:
            t.days_7_notified = True
        elif notify == 1:
            t.day_1_notified = True
        t.date_notified = utc_now
        userquery = self.bot.db.users.find({'tasks_assigned': td['task_name'], 'server_id': td['server_id']})
        if userquery:
            for limiter, utd in enumerate([tasks async for tasks in userquery]):
                t.users_from_dict(utd)

        await t.user_role()
        await t.save_task_to_db()
        print(t.user_list)
        if t.user_list:
            for i in t.user_list:
                await t.post_embed(i)

        # Check if TaskMaster is still present on the server
        if not t.server:
            return
        # Check if poll was activated and inform the sever if the poll is less than 2 hours past due
        # (activating old polls should only happen if the bot was offline for an extended period)
        if t.task_complete:
            return

    @tasks.loop(seconds=45)
    async def user_auto_notifications(self):
        if hasattr(self.bot, 'db'):
            utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

            # one day left notification
            query = self.bot.db.tasks.find({'task_complete': False, 'deadline': {
                '$lte': utc_now + datetime.timedelta(days=7)
            }})
            if query:
                for limit, td in enumerate([tasks async for tasks in query]):

                    if utc_now + datetime.timedelta(days=1) >= td['deadline'].replace(tzinfo=pytz.utc) >= td[
                        'date_created'].replace(tzinfo=pytz.utc) + datetime.timedelta(days=1) and td[
                        'day_1_notified'] == False:
                        await self.notify_user(td, 1, utc_now)
                    if utc_now + datetime.timedelta(days=7) >= td['deadline'].replace(tzinfo=pytz.utc) >= td[
                        'date_created'].replace(tzinfo=pytz.utc) + datetime.timedelta(days=7) and td[
                        'days_7_notified'] == False:
                        await self.notify_user(td, 7, utc_now)

    async def startup_notifications(self):
        if hasattr(self.bot, 'db'):
            utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

            # one day left notification
            query = self.bot.db.tasks.find({'task_complete': False})
            if query:
                for limit, td in enumerate([tasks async for tasks in query]):
                    await self.notify_user(td, 0, utc_now)

    @staticmethod
    def get_label(message: discord.Message):
        label = None
        if message and message.embeds:
            embed = message.embeds[0]
            label_object = embed.author
            if label_object:
                label_full = label_object.name
                if label_full and label_full.startswith('>> '):
                    label = label_full[3:]
        return label

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, data):
        # dont look at bot's own reactions
        user_id = data.user_id
        if user_id == self.bot.user.id:
            return

        # get emoji symbol
        emoji = data.emoji
        # if emoji:
        #     emoji_name = emoji.name
        if not emoji:
            return

        # check if we can find a task label
        message_id = data.message_id
        channel_id = data.channel_id
        channel = self.bot.get_channel(channel_id)

        if isinstance(channel, discord.TextChannel):
            server = channel.guild
            user = server.get_member(user_id)
            message = self.bot.message_cache.get(message_id)
            if message is None:
                try:
                    message = await channel.fetch_message(id=message_id)
                except discord.errors.Forbidden:
                    # Ignore Missing Access error
                    return
                self.bot.message_cache.put(message_id, message)
            label = self.get_label(message)
            if not label:
                return
        elif isinstance(channel, discord.DMChannel):
            user = await self.bot.fetch_user(user_id)  # only do this once
            message = self.bot.message_cache.get(message_id)
            if message is None:
                message = await channel.fetch_message(id=message_id)
                self.bot.message_cache.put(message_id, message)
            label = self.get_label(message)
            if not label:
                return
            server = await ask_for_server(self.bot, message, label)
        elif not channel:
            # discord rapidly closes dm channels by design
            # put private channels back into the bots cache and try again
            user = await self.bot.fetch_user(user_id)  # only do this once
            await user.create_dm()
            channel = self.bot.get_channel(channel_id)
            message = self.bot.message_cache.get(message_id)
            if message is None:
                message = await channel.fetch_message(id=message_id)
                self.bot.message_cache.put(message_id, message)
            label = self.get_label(message)
            if not label:
                return
            server = await ask_for_server(self.bot, message, label)
        else:
            return

        t = await Task.load_from_db(self.bot, server.id, label)
        if not isinstance(t, Task):
            return
        member = server.get_member(user_id)

        if emoji.name == '✅':
            if not isinstance(channel, discord.DMChannel):
                self.ignore_next_removed_reaction[str(message.id) + str(emoji)] = user_id
                self.bot.loop.create_task(message.remove_reaction(emoji, member))  # remove reaction

            t.task_complete = True
            await t.save_task_to_db()
            await t.refresh(message)
            print(emoji)
            # # sending file
            # file_name = await p.export()
            # if file_name is not None:
            #     self.bot.loop.create_task(user.send('Sending you the requested export of "{}".'.format(p.short),
            #                                         file=discord.File(file_name)
            #                                         )
            #                               )
            return
        if emoji.name == '❌':
            if not isinstance(channel, discord.DMChannel):
                self.ignore_next_removed_reaction[str(message.id) + str(emoji)] = user_id
                self.bot.loop.create_task(message.remove_reaction(emoji, member))  # remove reaction

            t.task_complete = False
            await t.save_task_to_db()
            await t.refresh(message)
        if emoji.name == '⏩':
            print("hello")

        if not t.has_required_role(member):
            await message.remove_reaction(emoji, user)
            await member.send(f'You are not allowed to vote in this poll. Only users with '
                              f'at least one of these roles can vote:\n{", ".join(t.roles)}')
            return

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, data):
        #later reverse function above
        await self.on_raw_reaction_add(data)


def setup(bot):
    global logger
    logger = logging.getLogger('discord')
    bot.add_cog(Notifications(bot))
