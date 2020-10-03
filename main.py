import json
import logging

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient

from commands import *

from discord.ext import commands, tasks

from commands import *
from commands.task import *

client = commands.Bot(command_prefix="/")
mydbcursor = None
logger = logging.getLogger('discord')

extensions = ['essentials.notifications']
for ext in extensions:
    client.load_extension(ext)


@client.event
async def on_ready():
    # mongodb below
    mongo = AsyncIOMotorClient(SETTINGS.mongo_db)
    client.db = mongo.taskmaster
    client.session = aiohttp.ClientSession()
    print(client.db)

    try:
        db_server_ids = [entry['_id'] async for entry in client.db.config.find({}, {})]
        for server in client.guilds:
            if str(server.id) not in db_server_ids:
                # create new config entry
                await client.db.config.update_one(
                    {'_id': str(server.id)},
                    {'$set': {'admin_role': 'taskadmin', 'user_role': 'taskuser'}},
                    upsert=True
                )
        for members in server.members:
            if members.bot:
                continue
            async for message in members.history():
                if message.author == client.user:
                    await message.delete()

    except Exception as e:
        print(e)

    with open('utils/emoji-compact.json', encoding='utf-8') as emojson:
        client.emoji_dict = json.load(emojson)


@client.command()
async def task(ctx, *args):
    if isinstance(ctx.channel, discord.channel.DMChannel):
        return

    if args[0] == "new":
        try:
            taskk = Task(client, ctx)
            taskk.wizard_messages.append(ctx.message)
            await taskk.set_task_description(ctx, args)
            await taskk.set_task_name(ctx)
            await taskk.set_deadline(ctx)
            taskk.task_notifications = 1
            await taskk.save_task_to_db()
            await taskk.save_user_task_to_db()
            await taskk.clean_up(ctx.channel)
            for i in taskk.user_list:
                await taskk.post_embed(i)
        except StopWizard:
            print("wizard stopped")
            await taskk.clean_up(ctx.channel)
        except TypeError:
            await taskk.clean_up(ctx.channel)
            print("wizard timed out")

    if args[0] == "assign":
        await ctx.send("not implemented yet")


client.run(SETTINGS.bot_token)