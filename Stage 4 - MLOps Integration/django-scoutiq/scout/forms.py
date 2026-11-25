from django import forms

from . import ml
from .models import Player

PHYSICAL_FIELDS = [
    "name",
    "height_in_cm",
    "international_caps",
    "position",
    "sub_position",
    "foot",
    "competition_code",
    "confederation",
]

PERFORMANCE_FIELDS = [
    "market_value_in_eur",
    "matches_played",
    "total_minutes",
    "total_goals",
    "total_assists",
    "yellow_cards",
    "red_cards",
]


class PlayerForm(forms.ModelForm):
    class Meta:
        model = Player
        fields = PHYSICAL_FIELDS + PERFORMANCE_FIELDS
        widgets = {
            "position": forms.Select(choices=[("", "Select position")] + list(Player._meta.get_field("position").choices)),
            "foot": forms.Select(choices=[("", "Select preferred foot")] + list(Player._meta.get_field("foot").choices)),
            "confederation": forms.Select(choices=[("", "Select confederation")] + list(Player._meta.get_field("confederation").choices)),
        }

    def to_features(self):
        return {k: self.cleaned_data[k] for k in ml.FEATURES}
