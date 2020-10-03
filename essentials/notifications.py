import datetime
import logging
from time import strftime

import discord
import pytz
from bson import ObjectId
from discord.ext import tasks, commands

from commands.task import Task


class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ignore_next_removed_reaction = {}
        self.index = 0
        self.user_auto_notifications.add_exception_type(KeyError)
        self.user_auto_notifications.start()

    async def user_notify(self):

        if hasattr(self.bot, 'db'):

            # one day left notification
            query = self.bot.db.tasks.find({'task_complete': False})
            if query:
                for limit, pd in enumerate([tasks async for tasks in query]):
                    # load task and update DB
                    t = Task(self.bot, load=True)
                    await t.task_from_dict(pd)
                    userquery = self.bot.db.users.find({'tasks_assigned': pd.get('task_name')})
                    if userquery:
                        for limiter, lspd in enumerate([tasks async for tasks in userquery]):
                            await t.users_from_dict(lspd)
                            for i in t.user_ids:
                                await t.post_embed(i)
                    else:
                        continue

                    # Check if TaskMaster is still present on the server
                    if not t.server:
                        continue
                    # Check if poll was activated and inform the sever if the poll is less than 2 hours past due
                    # (activating old polls should only happen if the bot was offline for an extended period)
                    if t.task_complete:
                        continue

    async def notify_user(self, td, notify, utc_now):
        print("got here ", td['task_name'])
        # load task and update DB
        t = Task(self.bot, load=True)
        print(t)
        await t.task_from_dict(td)
        if notify == 7:
            t.days_7_notified = True
        elif notify == 1:
            t.day_1_notified = True
        t.date_notified = utc_now
        await t.save_task_to_db()
        userquery = self.bot.db.users.find({'tasks_assigned': td['task_name']})
        if userquery:
            for limiter, utd in enumerate([tasks async for tasks in userquery]):
                await t.users_from_dict(utd)
                for i in t.user_list:
                    print(td['task_name'])
                    await t.post_embed(i)
        else:
            return

        # Check if TaskMaster is still present on the server
        if not t.server:
            return
        # Check if poll was activated and inform the sever if the poll is less than 2 hours past due
        # (activating old polls should only happen if the bot was offline for an extended period)
        if t.task_complete:
            return

    @tasks.loop(seconds=25)
    async def user_auto_notifications(self):
        if hasattr(self.bot, 'db'):
            utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

            # one day left notification
            query = self.bot.db.tasks.find({'task_complete': False, 'deadline': {
                '$lte': utc_now + datetime.timedelta(days=7)
            }})
            if query:
                for limit, td in enumerate([tasks async for tasks in query]):

                    if td['date_created'].replace(tzinfo=pytz.utc) + datetime.timedelta(days=1) <= td['deadline'].replace(tzinfo=pytz.utc) \
                            <= utc_now + datetime.timedelta(days=1) <= td['deadline'].replace(tzinfo=pytz.utc) + datetime.timedelta(seconds=30):
                        await self.notify_user(td, 1, utc_now)
                    if td['deadline'].replace(tzinfo=pytz.utc) + datetime.timedelta(seconds=30) >= utc_now + datetime.timedelta(days=7) >= \
                            td['deadline'].replace(tzinfo=pytz.utc) >= td['date_created'].replace(tzinfo=pytz.utc) + datetime.timedelta(days=7):
                        await self.notify_user(td, 7, utc_now)
                # if td['deadline'].replace(tzinfo=pytz.utc) <= utc_now + datetime.timedelta(days=7) and not \
                    #         td['deadline'].replace(tzinfo=pytz.utc) <= utc_now + datetime.timedelta(days=1) and td['task_notifications'] == 1:
                    #     await self.notify_user(td, 2)
                    #     print("notify 7")

            # query = self.bot.db.tasks.find({'task_complete': False, 'deadline': {
            #     '$gte': utc_now,
            #     '$lte': utc_now + datetime.timedelta(days=1)
            # }})
            # if query:
            #     for limit, td in enumerate([tasks async for tasks in query]):
            #         print(td['task_name'])
            #
            #         if td['deadline'].replace(tzinfo=pytz.utc) <= utc_now + datetime.timedelta(days=1) and td['task_notifications'] == 2:
            #             await self.notify_user(td, 3)
            #             print("notify 1")


def setup(bot):
    global logger
    logger = logging.getLogger('discord')
    bot.add_cog(Notifications(bot))
