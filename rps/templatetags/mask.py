from django import template

register = template.Library()

@register.filter
def mask_last(value, count=3):
    """
    Скрывает последние count символов
    alexander -> alexand***
    bo -> **
    """
    if not value:
        return ""

    value = str(value)
    if len(value) <= count:
        return "*" * len(value)

    return value[:-count] + "*" * count
