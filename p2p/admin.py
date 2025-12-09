from django.contrib import admin
from .models import Order, PriceHistory, P2PSettings

admin.site.register(Order)

@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('date', 'price')
    list_filter = ('date',)
    ordering = ('-date',)

@admin.register(P2PSettings)
class P2PSettingsAdmin(admin.ModelAdmin):
    list_display = ("is_market_open",)

