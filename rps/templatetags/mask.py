from django import template

register = template.Library()

@register.filter
def mask_last(value, count=3):
    """
    Скрывает последние count символов.
    Работает с @username, числами и объектами.

    alexander      -> alexand***
    @alexander     -> @alexand***
    bo             -> **
    12345          -> 12***
    """
    if not value:
        return ""

    s = str(value).strip()

    # сохраняем @ если есть
    prefix = ""
    if s.startswith("@"):
        prefix = "@"
        s = s[1:]

    if len(s) <= count:
        return prefix + ("*" * len(s))

    return prefix + s[:-count] + ("*" * count)
