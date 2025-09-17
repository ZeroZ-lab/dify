"""Unit tests covering workflow moderation feature support."""

import json
from uuid import uuid4

import pytest

from core.app.apps.workflow.app_config_manager import WorkflowAppConfigManager
from extensions.ext_code_based_extension import code_based_extension
from models.model import App, AppMode
from models.workflow import Workflow, WorkflowType


@pytest.fixture
def moderation_feature_config():
    return {
        "file_upload": {"enabled": False},
        "text_to_speech": {"enabled": False},
        "sensitive_word_avoidance": {
            "enabled": True,
            "type": "keywords",
            "config": {
                "keywords": "red flag",
                "inputs_config": {"enabled": True, "preset_response": "Input blocked"},
                "outputs_config": {"enabled": True, "preset_response": "Output blocked"},
            },
        },
    }


def test_config_validate_accepts_sensitive_word_avoidance(moderation_feature_config):
    code_based_extension.init()

    validated = WorkflowAppConfigManager.config_validate(
        tenant_id=str(uuid4()),
        config=json.loads(json.dumps(moderation_feature_config)),
        only_structure_validate=False,
    )

    assert validated["sensitive_word_avoidance"]["enabled"] is True
    assert validated["sensitive_word_avoidance"]["config"]["keywords"] == "red flag"


def test_get_app_config_returns_sensitive_word_avoidance_entity(moderation_feature_config):
    code_based_extension.init()

    app = App()
    app.id = str(uuid4())
    app.tenant_id = str(uuid4())
    app.mode = AppMode.WORKFLOW.value

    workflow = Workflow()
    workflow.id = str(uuid4())
    workflow.tenant_id = app.tenant_id
    workflow.app_id = app.id
    workflow.type = WorkflowType.WORKFLOW.value
    workflow.graph = json.dumps({"nodes": [], "edges": []})
    workflow.features = json.dumps(moderation_feature_config)

    app_config = WorkflowAppConfigManager.get_app_config(app_model=app, workflow=workflow)

    assert app_config.sensitive_word_avoidance is not None
    assert app_config.sensitive_word_avoidance.type == "keywords"
    assert app_config.sensitive_word_avoidance.config["keywords"] == "red flag"
