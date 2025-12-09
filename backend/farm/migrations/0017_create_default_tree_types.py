from django.db import migrations

def create_default_tree_types(apps, schema_editor):
    TreeType = apps.get_model('farm', 'TreeType')
    
    # Создаем базовое дерево (бесплатное)
    TreeType.objects.create(
        name="Обычное дерево",
        description="Базовое дерево для всех пользователей",
        price_ton=0,
        hourly_income_multiplier=1.0,
        is_default=True,
        image_level_1="tree1.png",
        image_level_2="tree2.png",
        image_level_3="tree3.png"
    )
    
    # Создаем премиум дерево
    TreeType.objects.create(
        name="Премиум дерево",
        description="Премиум дерево с увеличенным доходом",
        price_ton=1.0,  # Цена 1 TON
        hourly_income_multiplier=2.0,  # Удвоенный доход
        is_default=False,
        image_level_1="premium_tree1.png",
        image_level_2="premium_tree2.png",
        image_level_3="premium_tree3.png"
    )

def remove_default_tree_types(apps, schema_editor):
    TreeType = apps.get_model('farm', 'TreeType')
    TreeType.objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [
        ('farm', '0016_treetype_treepurchasetransaction_tree_tree_type'),
    ]

    operations = [
        migrations.RunPython(create_default_tree_types, remove_default_tree_types),
    ] 