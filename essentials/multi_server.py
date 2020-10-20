import asyncio

import discord

from essentials.settings import SETTINGS


async def get_servers(bot, message, task_name=None):
    """Get best guess of relevant shared servers"""
    if message.guild is None:
        list_of_shared_servers = []
        for s in bot.guilds:
            if message.author.id in [m.id for m in s.members]:
                list_of_shared_servers.append(s)
        if task_name is not None:
            query = bot.db.tasks.find({'task_name': task_name})
            if query is not None:
                server_ids_with_task_name = [task['server_id'] async for task in query]
                servers_with_short = [bot.get_guild(x) for x in server_ids_with_task_name]
                shared_servers_with_short = list(set(servers_with_short).intersection(set(list_of_shared_servers)))
                if shared_servers_with_short.__len__() >= 1:
                    return shared_servers_with_short

        # do this if no shared server with short is found
        if list_of_shared_servers.__len__() == 0:
            return []
        else:
            return list_of_shared_servers
    else:
        return [message.guild]


async def ask_for_server(bot, message, short=None):
    server_list = await get_servers(bot, message, short)
    if server_list.__len__() == 0:
        if short == None:
            await bot.say(
                'I could not find a common server where we can see eachother. If you think this is an error, '
                'please contact the developer.')
        else:
            await bot.say(f'I could not find a server where the poll {short} exists that we both can see.')
        return None
    elif server_list.__len__() == 1:
        return server_list[0]
    else:
        text = 'I\'m not sure which server you are referring to. Please tell me by typing the corresponding number.\n'
        i = 1
        for name in [s.name for s in server_list]:
            text += f'\n**{i}** - {name}'
            i += 1
        embed = discord.Embed(title="Select your server", description=text, color=SETTINGS.color)
        await message.channel.send(embed=embed)

        valid_reply = False
        nr = 1
        while not valid_reply:
            def check(m):
                return message.author == m.author
            try:
                reply = await bot.wait_for('message', timeout=120, check=check)
            except asyncio.TimeoutError:
                pass
            else:
                if reply and reply.content:
                    if reply.content.startswith("/") or reply.content.startswith("!"):
                        # await bot.say('You can\'t use bot commands while I am waiting for an answer.'
                        #               '\n I\'ll stop waiting and execute your command.')
                        return False
                    if str(reply.content).isdigit():
                        nr = int(reply.content)
                        if 0 < nr <= server_list.__len__():
                            valid_reply = True

        return server_list[nr - 1]