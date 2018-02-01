import os
from wandb import __stage_dir__


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard to guess string'
    BOARD_ADMIN = os.environ.get('BOARD_ADMIN')
    SSL_REDIRECT = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = True
    #SERVER_NAME = "localhost:7177"

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True


class ProductionConfig(Config):
    pass


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
