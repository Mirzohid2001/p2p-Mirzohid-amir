DEBUG = True
SMS_CODE_ACTIVE = False
ESKIZ_TOKEN = ""

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'p2pzaybal',
        'USER': 'postgres',
        'PASSWORD': '20010508',
        'HOST': 'localhost',
        'PORT': 5432,
    }
}

EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
SERVER_EMAIL = EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

PAYME_LOGIN = 'Paycom'
PAYME_PASSWORD = 'hxkgSChRGD2SW91N%JtOWJoRt6g3SiX1fX?V'

# For logging queries
# LOGGING = {
#     'version': 1,
#     'filters': {
#         'require_debug_true': {
#             '()': 'django.utils.log.RequireDebugTrue',
#         }
#     },
#     'handlers': {
#         'console': {
#             'level': 'DEBUG',
#             'filters': ['require_debug_true'],
#             'class': 'logging.StreamHandler',
#         }
#     },
#     'loggers': {
#         'django.db.backends': {
#             'level': 'DEBUG',
#             'handlers': ['console'],
#         }
#     }
# }
