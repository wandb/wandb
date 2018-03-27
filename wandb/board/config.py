import os


class Config:
    BOARD_ADMIN = os.environ.get('BOARD_ADMIN')
    SSL_REDIRECT = False
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
