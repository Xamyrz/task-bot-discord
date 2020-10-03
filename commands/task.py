import asyncio
import datetime
import logging
import os
import sys
import traceback
from string import ascii_lowercase

import dateparser
import pytz
import regex
from functools import reduce
from operator import contains, or_

import discord
from bson import ObjectId
from matplotlib import rcParams
from matplotlib.afm import AFM

from pytz import timezone, UnknownTimeZoneError
from unidecode import unidecode

from essentials.exceptions import *
from essentials.settings import SETTINGS

# Helvetica is the closest font to Whitney (discord uses Whitney) in afm
# This is used to estimate text width and adjust the layout of the embeds
from utils.misc import possible_timezones

afm_fname = os.path.join(rcParams['datapath'], 'fonts', 'afm', 'phvr8a.afm')
with open(afm_fname, 'rb') as fh:
    afm = AFM(fh)

AZ_EMOJIS = [(b'\\U0001f1a'.replace(b'a', bytes(hex(224 + (6 + i))[2:], "utf-8"))).decode("unicode-escape") for i in
             range(26)]


class Task:

    def __init__(self, client, ctx=None, load=False, server=None):
        self.bot = client
        self.cursor_pos = 0

        self.user_ids = []
        self.user_list = []

        if not load and ctx:
            if server is None:
                server = ctx.message.guild
            self.server = server
            self.author = ctx.message.author
            self.wizard_messages = []

            self.id = None
            self.task_id = None
            self.task_name = None
            self.task_description = None
            self.date_created = None
            self.deadline = None
            self.deadline_tz = 1
            self.task_complete = False
            self.days_7_notified = False
            self.day_1_notified = False
            self.date_notified = None
            self.last_notified = None

            self.tasks_assigned = []

    @staticmethod
    def get_preset_options():
        return ['✅', '🤐', '❎']

    async def clean_up(self, channel):
        if isinstance(channel, discord.TextChannel):
            self.bot.loop.create_task(channel.delete_messages(self.wizard_messages))

    async def wizard_says(self, ctx, text, footer=True):
        embed = discord.Embed(title="task creation Wizard", description=text, color=SETTINGS.color)
        if footer:
            embed.set_footer(text="Type `stop` to cancel the wizard.")
        msg = await ctx.send(embed=embed)
        self.wizard_messages.append(msg)
        return msg

    async def task_from_dict(self, d):
        self.id = ObjectId(str(d['_id']))
        self.server = self.bot.get_guild(int(d['server_id']))
        if self.server:
            self.author = self.server.get_member(int(d['task_author']))
        else:
            self.author = None
        self.task_description = d['task_description']
        self.task_name = d['task_name']
        self.date_created = d['date_created']
        self.deadline = d['deadline']
        self.deadline_tz = d['deadline_tz']
        self.days_7_notified = d['days_7_notified']
        self.day_1_notified = d['day_1_notified']
        self.date_notified = d['date_notified']
        self.cursor_pos = 0
        self.task_complete = d['task_complete']

    async def users_from_dict(self, d):
        self.user_list.append(self.server.get_member(int(d['user_id'])))

    async def task_to_dict(self):
        return ({
            'server_id': str(self.server.id),
            'task_name': self.task_name,
            'task_author': str(self.author.id),
            'task_description': self.task_description,
            'date_created': self.date_created,
            'deadline_tz': self.deadline_tz,
            'deadline': self.deadline,
            'task_complete': self.task_complete,
            'days_7_notified': self.days_7_notified,
            'day_1_notified': self.day_1_notified,
            'date_notified': self.date_notified
        })

    async def save_task_to_db(self):
        try:
            await self.bot.db.tasks.update_one({'server_id': str(self.server.id), 'task_name': self.task_name},
                                           {'$set': await self.task_to_dict()}, upsert=True)
            print("got here....")
        except Exception as e:
            logging.error(traceback.format_exc())
            print(e)
        print("server id ",self.server.id)

    async def user_task_to_dict(self):
        return ({
            'tasks_assigned': self.task_name,
        })

    async def save_user_task_to_db(self):
        if not self.user_ids:
            return
        for x in self.user_ids:
            print(x)
            await self.bot.db.users.update_one({'user_id': str(x), 'server_id': str(self.server.id)},
                                               {'$addToSet': await self.user_task_to_dict()}, upsert=True)

    async def is_complete(self, update_db=True):
        if self.server is None:
            self.task_complete = False
            return
        if not self.task_complete and self.deadline != 0 \
                and datetime.datetime.utcnow().replace(tzinfo=pytz.utc) > self.get_deadline_with_tz():
            self.task_complete = True
            if update_db:
                await self.save_task_to_db()
        return self.task_complete

    async def is_valid_id(self, user):
        set = '<@!>'
        return reduce(or_, map(contains, len(set) * [user], set))

    async def get_user_reply(self, ctx):
        def is_correct(m):
            return m.author != self.bot.user and m.author == self.author

        try:
            reply = await self.bot.wait_for('message', check=is_correct, timeout=300)
        except asyncio.TimeoutError:
            return await self.wizard_says(ctx, f'Task wizard timed out..\n'
                                               f'took too long to respond',
                                          footer=False)

        if reply and reply.content:
            if reply.content.startswith("/") or reply.content.startswith("!"):
                await self.wizard_says(ctx, f'You can\'t use bot commands during the Task Creation Wizard.\n'
                                            f'Stopping the Wizard and then executing the command:\n`{reply.content}`',
                                       footer=False)
                raise StopWizard
            elif reply.content.lower() == 'stop':
                self.wizard_messages.append(reply)
                await self.wizard_says(ctx, 'Task Wizard stopped.', footer=False)
                raise StopWizard
            else:
                self.wizard_messages.append(reply)
                return reply.content
        else:
            await self.wizard_says(ctx, "Invalid input...")

    async def wizard_says_edit(self, message, text, stop=True, add=False):
        if add and message.embeds.__len__() > 0:
            text = message.embeds[0].description + text
        embed = discord.Embed(title="Task creation Wizard", description=text, color=SETTINGS.color)
        if stop:
            embed.set_footer(text="Type `stop` to cancel the wizard.")
        return await message.edit(embed=embed)

    async def add_error(self, message, error, stop=True):
        text = ''
        if message.embeds.__len__() > 0:
            text = message.embeds[0].description + '\n\n:exclamation: ' + error
        if not stop:
            return await self.wizard_says_edit(message, text, stop)
        return await self.wizard_says_edit(message, text)

    async def add_vaild(self, message, string):
        text = ''
        if message.embeds.__len__() > 0:
            text = message.embeds[0].description + '\n\n✅ ' + string
        return await self.wizard_says_edit(message, text)

    def get_deadline_with_tz(self):
        if self.deadline == 0:
            return 0
        elif isinstance(self.deadline, datetime.datetime):
            dt = self.deadline
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                dt = pytz.utc.localize(dt)
            if isinstance(self.deadline_tz, float):
                tz = possible_timezones(self.deadline_tz, common_only=True)
                if not tz:
                    tz = pytz.timezone('UTC')
                else:
                    # choose one valid timezone with the offset
                    try:
                        tz = pytz.timezone(tz[0])
                    except UnknownTimeZoneError:
                        tz = pytz.UTC
            else:
                try:
                    tz = pytz.timezone(self.deadline_tz)
                except UnknownTimeZoneError:
                    tz = pytz.UTC

            return dt.astimezone(tz)

    async def get_deadline(self, string=False):
        if self.deadline == 0:
            if string:
                return 'No deadline'
            else:
                return 0
        else:
            deadline = self.get_deadline_with_tz()
            if string:
                return deadline.strftime('%d-%b-%Y %H:%M %Z')
            else:
                return deadline

    @staticmethod
    def sanitize_string(string):
        """Sanitize user input for wizard"""
        # sanitize input
        if string is None:
            raise InvalidInput
        string = regex.sub("\p{C}+", "", string)
        if set(string).issubset(set(' ')):
            raise InvalidInput
        return string

    async def set_task_description(self, ctx, args, force=None):

        async def get_valid(in_reply):
            if not in_reply:
                raise InvalidInput
            min_len = 3
            max_len = 400
            in_reply = self.sanitize_string(in_reply)
            if not in_reply:
                raise InvalidInput
            elif min_len <= in_reply.__len__() <= max_len:
                return in_reply
            else:
                raise InvalidInput

        async def check_users():
            j = 0
            # check for the same user in array
            if len(set(users)) != len(users):
                return -1
            for member in ctx.guild.members:
                if j >= args.__len__() - 1:
                    break
                if member.id == users[j]:
                    j += 1
                    print(f"{member.id} {member.display_name} found")
            return j

        async def users_to_int():
            # removes unnecesary characters in the id
            usrs = []
            for x in range(1, args.__len__()):
                print(x)
                if not await self.is_valid_id(args[x]):
                    return await self.wizard_says(ctx, str(f"Invalid User: {args[x]}"), footer=False)
                usrs.append(int(args[x].translate({ord(i): None for i in '<@!>'})))
            return usrs

        users = await users_to_int()
        if args.__len__() - 1 == await check_users():
            try:
                self.task_name = await get_valid(force)
                return
            except InputError:
                pass
            print(datetime.datetime.now(timezone('Europe/Dublin')).strftime("%Y-%m-%d %H:%M:%S"))
            message = await self.wizard_says(ctx, f'Please enter the task description.\n',
                                             footer=True)
            while True:
                try:
                    if force:
                        reply = force
                        force = None
                    else:
                        reply = await self.get_user_reply(ctx)
                    self.task_description = await get_valid(reply)
                    self.user_ids = users
                    await self.add_vaild(message, self.task_description)
                    break
                except InvalidInput:
                    await self.add_error(message, '**Keep the task description between 3 and 400 valid characters**')
            for usr in self.user_ids:
                self.user_list.append(self.server.get_member(int(usr)))

        else:
            errormsg = await self.wizard_says(ctx, str(f"TASK CREATION ERROR"), footer=False)
            await self.add_error(errormsg, '**Can\'t assign the same task to one user multiple times**', False)
            raise StopWizard

    async def set_task_name(self, ctx, force=None):

        async def get_valid(in_reply):
            if not in_reply:
                raise InvalidInput
            min_len = 2
            max_len = 25
            in_reply = self.sanitize_string(in_reply)
            if not in_reply:
                raise InvalidInput
            elif await self.bot.db.tasks.find_one(
                    {'server_id': str(self.server.id), 'task_name': in_reply}) is not None:
                raise DuplicateInput
            elif min_len <= in_reply.__len__() <= max_len and in_reply.split(" ").__len__() == 1:
                return in_reply
            else:
                raise InvalidInput

        try:
            self.task_name = await get_valid(force)
            return
        except InputError:
            pass
            print(datetime.datetime.now(timezone('Europe/Dublin')).strftime("%Y-%m-%d %H:%M:%S"))
            message = await self.wizard_says(ctx, """**Now type a unique one word identifier, a label, 
            for your poll.** This label will be used to refer to the task. Keep it short and significant.""",
                                             footer=True)
            while True:
                try:
                    if force:
                        reply = force
                        force = None
                    else:
                        reply = await self.get_user_reply(ctx)
                    self.task_name = await get_valid(reply)
                    await self.add_vaild(message, reply)
                    break
                except InvalidInput:
                    await self.add_error(message, '**Keep the task name between 2 and 25 valid characters**')
                except DuplicateInput:
                    await self.add_error(message,
                                         f'**The label `{reply}` is not unique on this server. Choose a different one!**')

    async def set_deadline(self, ctx, force=None):

        async def get_valid(in_reply):
            if not in_reply:
                raise InvalidInput
            in_reply = self.sanitize_string(in_reply)
            if not in_reply:
                raise InvalidInput
            elif in_reply == '0':
                return 0

            dt = dateparser.parse(in_reply)
            if not isinstance(dt, datetime.datetime):
                raise InvalidInput

            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                dt = dt.astimezone(
                    timezone('Europe/Dublin'))  # can be changed later, setting timezone to for dublin now

            now = datetime.datetime.utcnow().astimezone(pytz.utc)

            if dt < now:
                raise DateOutOfRange(dt)
            return dt

        if str(force) == '-1':
            return

        try:
            dt = await get_valid(force)
            self.deadline = dt
            self.date_created = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
            if self.deadline != 0:
                self.deadline_tz = dt.utcoffset().total_seconds() / 3600
            return
        except InputError:
            pass

        text = ("The task will have no deadline if not set, you can set the deadline at certain date. "
                "**Type `0` to set no deadline or tell me when you want the deadline to be** by "
                "typing an absolute or relative date. You can specify a timezone if you want.\n"
                "Examples: `in 2 days`, `next week CET`, `may 3rd 2019`, `9.11.2019 9pm EST` ")
        message = await self.wizard_says(ctx, text)

        while True:
            try:
                if force:
                    reply = force
                    force = None
                else:
                    reply = await self.get_user_reply(ctx)
                dt = await get_valid(reply)
                self.deadline = dt
                if self.deadline == 0:
                    await self.add_vaild(message, 'no deadline')
                else:
                    self.deadline_tz = dt.utcoffset().total_seconds() / 3600
                    print("deadlinetz ", self.deadline_tz)
                    self.date_created = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
                    await self.add_vaild(message, self.deadline.strftime('%d-%b-%Y %H:%M %Z'))
                break
            except InvalidInput:
                await self.add_error(message, '**Specify the deadline time in a format i can understand.**')
            except TypeError:
                await self.add_error(message, '**Type Error.**')
            except DateOutOfRange as e:
                await self.add_error(message, f'**{e.date.strftime("%d-%b-%Y %H:%M")} is in the past.**')

    def add_field_custom(self, name, value, embed):
        """this is used to estimate the width of text and add empty embed fields for a cleaner report
        cursor_pos is used to track if we are at the start of a new line in the report. Each line has max 2 slots for info.
        If the line is short, we can fit a second field, if it is too long, we get an automatic linebreak.
        If it is in between, we create an empty field to prevent the inline from looking ugly"""

        name = str(name)
        value = str(value)

        nwidth = afm.string_width_height(unidecode(name))
        vwidth = afm.string_width_height(unidecode(value))
        w = max(nwidth[0], vwidth[0])

        embed.add_field(name=name, value=value, inline=False if w > 12500 and self.cursor_pos % 2 == 1 else True)
        self.cursor_pos += 1

        # create an empty field if we are at the second slot and the
        # width of the first slot is between the critical values
        if self.cursor_pos % 2 == 1 and 11600 < w < 20000:
            embed.add_field(name='\u200b', value='\u200b', inline=True)
            self.cursor_pos += 1

        return embed

    async def generate_embed(self):
        """Generate Discord Report"""
        self.cursor_pos = 0
        embed = discord.Embed(title='', colour=SETTINGS.color)  # f'Status: {"Open" if self.is_open() else "Closed"}'
        embed.set_author(name=f' >> {self.task_name} ',
                         icon_url=SETTINGS.author_icon)
        embed.set_thumbnail(url=SETTINGS.report_icon)

        # ## adding fields with custom, length sensitive function

        embed = self.add_field_custom(name='**Task description**', value=self.task_description, embed=embed)

        if self.deadline != 0:
            embed = self.add_field_custom(name='**Deadline**', value=await self.get_deadline(string=True), embed=embed)
        else:
            embed = self.add_field_custom(name='**Deadline**', value="No deadline", embed=embed)

        return embed

    async def post_embed(self, destination):
        msg = await destination.send(embed=await self.generate_embed())
        if not await self.is_complete():
            for i in self.get_preset_options():
                await msg.add_reaction(i)
            return msg
        else:
            return msg
