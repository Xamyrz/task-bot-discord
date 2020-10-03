import discord


class Settings:
    def __init__(self):
        self.color = discord.Colour(int('72da8e', 16))
        self.title_icon = "https://i.imgur.com/vtLsAl8.jpg" #PM
        self.author_icon = "https://i.imgur.com/TYbBtwB.jpg" #tag
        self.report_icon = "https://i.imgur.com/YksGRLN.png" #report
        self.owner_id = 117687652278468610
        self.msg_errors = False
        self.log_errors = True
        self.invite_link = \
            'link_here'

        self.load_secrets()

    def load_secrets(self):
        # secret
        self.dbl_token = ''
        self.mongo_db = MONGO_
        self.bot_token = TOKEN_HERE
        self.mode = 'development'


SETTINGS = Settings()