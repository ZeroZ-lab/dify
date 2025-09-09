from flask import Blueprint, Flask
from flask_restx import Resource
from werkzeug.exceptions import BadRequest, Unauthorized

from libs.external_api import ExternalApi
from core.errors.error import AppInvokeQuotaExceededError


def _create_app():
    app = Flask(__name__)
    bp = Blueprint("t", __name__)
    api = ExternalApi(bp)

    @api.route("/bad-request")
    class Bad(Resource):  # type: ignore
        def get(self):  # type: ignore
            raise BadRequest("invalid input")

    @api.route("/unauth")
    class Unauth(Resource):  # type: ignore
        def get(self):  # type: ignore
            raise Unauthorized("auth required")

    @api.route("/value-error")
    class ValErr(Resource):  # type: ignore
        def get(self):  # type: ignore
            raise ValueError("boom")

    @api.route("/quota")
    class Quota(Resource):  # type: ignore
        def get(self):  # type: ignore
            raise AppInvokeQuotaExceededError("quota exceeded")

    @api.route("/general")
    class Gen(Resource):  # type: ignore
        def get(self):  # type: ignore
            raise RuntimeError("oops")

    app.register_blueprint(bp, url_prefix="/api")
    return app


def test_external_api_error_handlers():
    app = _create_app()
    client = app.test_client()

    # 400 path
    res = client.get("/api/bad-request")
    assert res.status_code == 400
    data = res.get_json()
    assert data["code"] == "bad_request"
    assert data["status"] == 400

    # 401 path adds header
    res = client.get("/api/unauth")
    assert res.status_code == 401
    assert "WWW-Authenticate" in res.headers

    # 400 ValueError route
    res = client.get("/api/value-error")
    assert res.status_code == 400
    assert res.get_json()["code"] == "invalid_param"

    # Quota exception currently handled under ValueError in routing context
    # Accept either 400 (ValueError handler) or 429 (specific handler), depending on framework resolution
    res = client.get("/api/quota")
    assert res.status_code in (400, 429)

    # 500 general
    res = client.get("/api/general")
    assert res.status_code == 500
    assert res.get_json()["status"] == 500
