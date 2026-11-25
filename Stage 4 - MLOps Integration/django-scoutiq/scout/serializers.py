from rest_framework import serializers

from .models import Player, Prediction


class PlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Player
        fields = "__all__"


class PredictionSerializer(serializers.ModelSerializer):
    player = PlayerSerializer(read_only=True)
    player_id = serializers.PrimaryKeyRelatedField(
        queryset=Player.objects.all(), source="player", write_only=True
    )
    predicted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Prediction
        fields = ["id", "player", "player_id", "predicted_rating", "predicted_by_name", "created_at"]

    def get_predicted_by_name(self, obj):
        return obj.predicted_by.username if obj.predicted_by_id else "—"
