import json
import logging
import uuid
from datetime import UTC, datetime

from flask import jsonify, request
from werkzeug.exceptions import NotFound, RequestEntityTooLarge

from controllers.trigger import bp
from extensions.ext_redis import redis_client
from services.webhook_service import WebhookService

logger = logging.getLogger(__name__)


@bp.route("/webhook/<string:webhook_id>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def handle_webhook(webhook_id: str):
    """
    Handle production webhook trigger calls.

    This endpoint receives webhook calls and processes them according to the
    configured webhook trigger settings.
    """
    try:
        # Get webhook trigger, workflow, and node configuration
        webhook_trigger, workflow, node_config = WebhookService.get_webhook_trigger_and_workflow(webhook_id)

        # Extract request data
        webhook_data = WebhookService.extract_webhook_data(webhook_trigger)

        # Validate request against node configuration
        validation_result = WebhookService.validate_webhook_request(webhook_data, node_config)
        if not validation_result["valid"]:
            return jsonify({"error": "Bad Request", "message": validation_result["error"]}), 400

        # Process webhook call (send to Celery)
        WebhookService.trigger_workflow_execution(webhook_trigger, webhook_data, workflow)

        # Return configured response
        response_data, status_code = WebhookService.generate_webhook_response(node_config)
        return jsonify(response_data), status_code

    except ValueError as e:
        raise NotFound(str(e))
    except RequestEntityTooLarge:
        raise
    except Exception as e:
        logger.exception("Webhook processing failed for %s", webhook_id)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@bp.route("/webhook-debug/<string:webhook_id>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def handle_webhook_debug(webhook_id: str):
    """
    Handle debug webhook trigger calls.

    This endpoint receives webhook calls for debugging purposes.
    It stores debug information and provides enhanced response details.
    """
    # Single-use session: if a debug_session is provided, we will consume it
    session_key: str | None = None
    try:
        # Get debug session ID from query parameter or header
        debug_session_id = request.args.get("debug_session") or request.headers.get("X-Debug-Session")
        if debug_session_id:
            session_key = f"debug_session:{debug_session_id}"
            # Validate session existence before processing; single-use semantics
            session_data = redis_client.get(session_key)
            if not session_data:
                return jsonify({"status": "not_found", "error": "Debug session not found or expired"}), 404

        # Get webhook trigger, workflow, and node configuration
        webhook_trigger, workflow, node_config = WebhookService.get_webhook_trigger_and_workflow(webhook_id)

        # Extract request data
        webhook_data = WebhookService.extract_webhook_data(webhook_trigger)

        # Validate request against node configuration
        validation_result = WebhookService.validate_webhook_request(webhook_data, node_config)
        if not validation_result["valid"]:
            debug_response = {
                "status": "validation_error",
                "webhook_id": webhook_id,
                "debug_session_id": debug_session_id,
                "error": validation_result["error"],
                "received_data": {
                    "method": request.method,
                    "headers": dict(request.headers),
                    "query_params": dict(request.args),
                    "body": webhook_data.get("body", {}),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            }
            return jsonify(debug_response), 400

        # Process webhook call in debug mode
        workflow_run_id = WebhookService.trigger_workflow_execution(
            webhook_trigger, webhook_data, workflow, is_debug=True, debug_session_id=debug_session_id
        )

        # Store debug information
        debug_info = {
            "webhook_id": webhook_id,
            "debug_session_id": debug_session_id,
            "tenant_id": webhook_trigger.tenant_id,
            "app_id": webhook_trigger.app_id,
            "received_at": datetime.now(UTC).isoformat(),
            "request": {
                "method": request.method,
                "headers": dict(request.headers),
                "query_params": dict(request.args),
                "body": webhook_data.get("body", {}),
            },
            "validation": validation_result,
            "workflow_run_id": workflow_run_id,
            "workflow_id": workflow.id,
            "node_id": webhook_trigger.node_id,
            "status": "processing",
        }

        # Store debug info in Redis for 1 hour
        debug_key = f"webhook_debug:{uuid.uuid4().hex}"
        redis_client.setex(debug_key, 3600, json.dumps(debug_info))

        # Return enhanced debug response
        debug_response = {
            "status": "success",
            "webhook_id": webhook_id,
            "debug_session_id": debug_session_id,
            "debug_key": debug_key,
            "workflow_run_id": workflow_run_id,
            "message": "Debug webhook processed successfully",
            "workflow_id": workflow.id,
            "node_id": webhook_trigger.node_id,
            "received_at": debug_info["received_at"],
            "request_summary": {
                "method": request.method,
                "content_type": request.headers.get("Content-Type", "unknown"),
                "body_size": len(str(webhook_data.get("body", {}))),
            },
        }

        return jsonify(debug_response), 200

    except ValueError as e:
        debug_response = {
            "status": "not_found",
            "webhook_id": webhook_id,
            "error": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return jsonify(debug_response), 404
    except Exception as e:
        logger.exception("Debug webhook processing failed for %s", webhook_id)
        debug_response = {
            "status": "error",
            "webhook_id": webhook_id,
            "error": "Internal server error",
            "details": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return jsonify(debug_response), 500
    finally:
        # Consume the session after any debug call if provided
        if session_key:
            try:
                redis_client.delete(session_key)
            except Exception:
                logger.exception("Failed to consume debug session %s", session_key)
