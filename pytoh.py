import os

base_locale = os.path.join(os.path.dirname(__file__), '..', 'locale')
for lang in os.listdir(base_locale):
    lc_messages = os.path.join(base_locale, lang, 'LC_MESSAGES')
    for fname in ['django.mo', 'django.po']:
        fpath = os.path.join(lc_messages, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print(f"Eliminado: {fpath}")