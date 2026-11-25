from django.contrib import admin

from .models import Player, Prediction


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "sub_position", "competition_code", "created_at")
    list_filter = ("position", "confederation", "competition_code")
    search_fields = ("name",)


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("player", "predicted_rating", "predicted_by", "created_at")
    list_filter = ("predicted_rating",)
