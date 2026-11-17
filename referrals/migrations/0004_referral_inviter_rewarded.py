from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0003_taskcompletion"),
    ]

    operations = [
        # старым приглашениям бонус уже выдан сразу при регистрации
        migrations.AddField(
            model_name="referral",
            name="inviter_rewarded",
            field=models.BooleanField(default=True, verbose_name="Бонус пригласившему выдан"),
        ),
        # новым — только после полива и игры КНБ
        migrations.AlterField(
            model_name="referral",
            name="inviter_rewarded",
            field=models.BooleanField(default=False, verbose_name="Бонус пригласившему выдан"),
        ),
    ]
