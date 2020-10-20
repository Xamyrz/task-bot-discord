from commands.task import Task


class Assign:
    def __init__(self, client, ctx):
        self.server = ctx.message.guild
        self.task_name = None
        self.bot = client

    async def assign_to(self, ctx, task_name):
        self.task_name = task_name
        query = await self.bot.db.tasks.find_one({'task_name': task_name, 'server_id': str(self.server.id)})
        t = Task(self.bot, ctx)
        userquery = self.bot.db.users.find({'tasks_assigned': task_name, 'server_id': str(self.server.id)})
        if query:
            await t.task_from_dict(query)
            if userquery:
                for limiter, utd in enumerate([tasks async for tasks in userquery]):
                    await t.users_from_dict(utd)
            await t.assign_task()
            await t.save_task_to_db()
            await t.save_user_task_to_db()
            await t.clean_up(ctx.channel)
        else:
            await ctx.send(f'**I can\'t find the task **{task_name}**.**')

        #await t.save_task_to_db()