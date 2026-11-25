from django.contrib.auth.models import User
from django.db import models

# Same vocabularies as the FastAPI track (fastapi-service/app.py),
# so predictions stay comparable across both backends.
POSITION_CHOICES = [
    ("Attack", "Attack"),
    ("Defender", "Defender"),
    ("Goalkeeper", "Goalkeeper"),
    ("Midfield", "Midfield"),
]

FOOT_CHOICES = [
    ("left", "Left"),
    ("right", "Right"),
    ("both", "Both"),
]

CONFEDERATION_CHOICES = [
    ("amerika", "America"),
    ("asien", "Asia"),
    ("europa", "Europe"),
]

RATING_CHOICES = [
    ("Outperforming", "Outperforming"),
    ("Average", "Average"),
    ("Underperforming", "Underperforming"),
]


class Player(models.Model):
    """One scouted footballer + the 14 model input fields."""

    name = models.CharField(max_length=120)

    # Numeric inputs (FloatField mirrors the FastAPI PlayerData schema)
    height_in_cm = models.FloatField()
    international_caps = models.FloatField()
    market_value_in_eur = models.FloatField()
    matches_played = models.FloatField()
    total_minutes = models.FloatField()
    total_goals = models.FloatField()
    total_assists = models.FloatField()
    yellow_cards = models.FloatField()
    red_cards = models.FloatField()

    # Categorical inputs
    position = models.CharField(max_length=20, choices=POSITION_CHOICES)
    sub_position = models.CharField(max_length=30)
    foot = models.CharField(max_length=10, choices=FOOT_CHOICES)
    competition_code = models.CharField(max_length=60)
    confederation = models.CharField(max_length=20, choices=CONFEDERATION_CHOICES)

    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="players"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.position} · {self.sub_position})"


class Prediction(models.Model):
    """A stored model verdict for a player (inputs live on Player)."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="predictions")
    predicted_rating = models.CharField(max_length=20, choices=RATING_CHOICES)
    predicted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="predictions"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.player.name} → {self.predicted_rating} ({self.created_at:%Y-%m-%d})"
