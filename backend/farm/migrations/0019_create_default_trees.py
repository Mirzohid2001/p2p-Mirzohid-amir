from django.db import migrations
from decimal import Decimal

def create_default_trees(apps, schema_editor):
    TreeType = apps.get_model('farm', 'TreeType')
    
    # Создаем базовое CF дерево (бесплатное)
    TreeType.objects.create(
        name="CF Дерево",
        description="Базовое дерево, приносящее CryptoFlora",
        price_ton=0,
        income_currency='CF',
        hourly_income=Decimal('1.0'),
        is_default=True,
        image_level_1="tree1.png",
        image_level_2="tree2.png",
        image_level_3="tree3.png"
    )
    
    # Создаем TON дерево (премиум)
    TreeType.objects.create(
        name="TON Дерево",
        description="Премиум дерево, приносящее TON",
        price_ton=Decimal('1.0'),
        income_currency='TON',
        hourly_income=Decimal('0.001'),
        is_default=False,
        image_level_1="ton_tree1.png",
        image_level_2="ton_tree2.png",
        image_level_3="ton_tree3.png"
    )

def remove_default_trees(apps, schema_editor):
    TreeType = apps.get_model('farm', 'TreeType')
    TreeType.objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [
        ('farm', '0018_remove_treetype_hourly_income_multiplier_and_more'),
    ]

    operations = [
        migrations.RunPython(create_default_trees, remove_default_trees),
    ] 