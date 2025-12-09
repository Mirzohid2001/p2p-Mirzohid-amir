from django import template
register = template.Library()

@register.filter
def mul(value, arg):
    return int(value) * int(arg)
