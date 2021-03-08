# Generated by Django 3.1.7 on 2021-03-02 18:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_add_asset_blob_size_field'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='asset',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='asset',
            name='versions',
            field=models.ManyToManyField(related_name='assets', to='api.Version'),
        ),
        migrations.RemoveField(
            model_name='asset',
            name='version',
        ),
        migrations.AddField(
            model_name='asset',
            name='previous',
            field=models.ForeignKey(
                default=None,
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='api.asset',
            ),
        ),
        migrations.AlterModelOptions(
            name='asset',
            options={'get_latest_by': 'modified'},
        ),
    ]
