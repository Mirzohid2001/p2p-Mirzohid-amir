from django import forms
from .models import Order

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['action', 'cf_amount']

    action = forms.ChoiceField(choices=Order.ACTIONS, label='Тип операции')
    cf_amount = forms.DecimalField(min_value=0.01, label='Сумма CF', decimal_places=2)
