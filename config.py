import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'solarai-ban-pong-2026-dss'
    DEBUG = True
    JSON_AS_ASCII = False   # Allow Thai characters in JSON responses
    JSON_SORT_KEYS = False
