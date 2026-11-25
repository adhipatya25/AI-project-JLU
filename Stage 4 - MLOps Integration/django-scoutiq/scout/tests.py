"""Tests for the Django -> FastAPI integration.

Run:  python manage.py test scout
- MockedServiceTests always run (FastAPI is faked).
- LiveServiceTests run only when the real FastAPI service answers on FASTAPI_URL.
"""

import json
import unittest
from unittest import mock

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from . import ml
from .models import Player, Prediction

FIELDS = {
    "height_in_cm": 187, "international_caps": 6, "market_value_in_eur": 500000,
    "matches_played": 197, "total_minutes": 15223, "total_goals": 7,
    "total_assists": 4, "yellow_cards": 38, "red_cards": 2,
    "position": "Defender", "sub_position": "Centre-Back", "foot": "right",
    "competition_code": "liga-portugal", "confederation": "europa",
}
SAMPLE = {"name": "Test Defender", **FIELDS}


def _fake_response(status=200, json_body=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = json_body or {}
    resp.text = ""
    return resp


def _post_json(client, url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json")


@mock.patch("scout.ml.requests.get", side_effect=requests.ConnectionError)  # /health
class MockedServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("scout", password="pw-12345-test")
        self.client.force_login(self.user)

    def test_page_renders_fastapi_style_ui(self, _get):
        resp = self.client.get("/")
        self.assertContains(resp, 'id="prediction-form"')
        self.assertContains(resp, "Predict directly from PDF")
        self.assertContains(resp, "Player snapshot")
        self.assertContains(resp, "FastAPI offline")

    @mock.patch("scout.ml.requests.post")
    def test_predict_calls_fastapi_and_stores(self, post, _get):
        post.return_value = _fake_response(json_body={"predicted_future_potential_rating": "Average"})
        resp = _post_json(self.client, "/ui/predict/", SAMPLE)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["predicted_future_potential_rating"], "Average")
        # link must open the HTML player record, not the REST API JSON
        self.assertEqual(data["player_url"], f"/players/{data['player_id']}/")
        url, body = post.call_args.args[0], post.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/predict"))
        self.assertEqual(set(body), set(ml.FEATURES))  # name is not sent to the model
        self.assertIsInstance(body["height_in_cm"], float)
        self.assertEqual(Prediction.objects.get().player.name, "Test Defender")

    @mock.patch("scout.ml.requests.post")
    def test_blank_name_gets_default(self, post, _get):
        post.return_value = _fake_response(json_body={"predicted_future_potential_rating": "Average"})
        _post_json(self.client, "/ui/predict/", {**FIELDS, "name": ""})
        self.assertEqual(Player.objects.get().name, "Player #1")

    @mock.patch("scout.ml.requests.post", side_effect=requests.ConnectionError)
    def test_service_down_returns_503_and_stores_nothing(self, _post, _get):
        resp = _post_json(self.client, "/ui/predict/", SAMPLE)
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Cannot reach the FastAPI model service", resp.json()["detail"])
        self.assertEqual(Player.objects.count(), 0)

    def test_invalid_form_returns_400(self, _get):
        resp = _post_json(self.client, "/ui/predict/", {**SAMPLE, "foot": "hand"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("foot", resp.json()["detail"])

    @mock.patch("scout.ml.requests.post")
    def test_csv_batch_stores_each_row(self, post, _get):
        post.return_value = _fake_response(json_body={"predicted_future_potential_rating": "Outperforming"})
        header = "name," + ",".join(ml.FEATURES)
        row = "A," + ",".join(str(FIELDS[k]) for k in ml.FEATURES)
        csv = SimpleUploadedFile("squad.csv", f"{header}\n{row}\n{row.replace('A,', 'B,', 1)}\n".encode())
        resp = self.client.post("/ui/predict-from-csv/", {"file": csv})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)
        self.assertEqual(Prediction.objects.count(), 2)

    @mock.patch("scout.pdfextract.extract_pdf_text", return_value="")
    @mock.patch("scout.pdfextract.parse_report_text",
                return_value={**{k: None for k in ml.FEATURES}, "height_in_cm": 180.0})
    @mock.patch("scout.ml.requests.post")
    def test_partial_pdf_uses_predict_partial_and_is_not_stored(self, post, _parse, _text, _get):
        post.return_value = _fake_response(json_body={"predicted_future_potential_rating": "Average"})
        pdf = SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake")
        resp = self.client.post("/ui/predict-from-report/", {"file": pdf})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(post.call_args.args[0].endswith("/predict-partial"))
        self.assertEqual(len(resp.json()["missing_fields_filled_by_model_median"]), 13)
        self.assertEqual(Player.objects.count(), 0)

    def test_api_requires_login_with_json_401(self, _get):
        self.client.logout()
        resp = _post_json(self.client, "/ui/predict/", SAMPLE)
        self.assertEqual(resp.status_code, 401)

    @mock.patch("scout.ml.requests.post")
    def test_unknown_rating_is_rejected(self, post, _get):
        post.return_value = _fake_response(json_body={"predicted_future_potential_rating": "Legend"})
        with self.assertRaises(ml.PredictionServiceError):
            ml.predict_player(FIELDS)


def _service_up():
    try:
        return requests.get(f"{settings.FASTAPI_URL}/health", timeout=2).ok
    except requests.RequestException:
        return False


@unittest.skipUnless(_service_up(), "FastAPI service not running on FASTAPI_URL")
class LiveServiceTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("live", password="pw-12345-test"))

    def test_real_prediction_round_trip(self):
        resp = _post_json(self.client, "/ui/predict/", SAMPLE)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(Prediction.objects.get().predicted_rating, ml.VALID_RATINGS)
        self.assertEqual(ml.service_health()["model"], "GradientBoostingClassifier")

    def test_real_partial_prediction(self):
        self.assertIn(ml.predict_partial({"height_in_cm": 180, "position": "Attack"}), ml.VALID_RATINGS)
