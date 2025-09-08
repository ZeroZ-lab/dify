import json
import logging
import uuid
from datetime import UTC, datetime

from flask_login import current_user
from flask_restx import Resource

from controllers.console.wraps import account_initialization_required, setup_required
from extensions.ext_redis import redis_client
from libs.login import login_required

logger = logging.getLogger(__name__)


class DebugSessionApi(Resource):
    """Debug session management API."""

    @setup_required
    @login_required
    @account_initialization_required
    def post(self):
        """Create a new debug session for webhook monitoring."""
        try:
            # Get tenant_id from current user
            tenant_id = current_user.current_tenant_id

            # Create debug session
            session_id = f"debug_session_{uuid.uuid4().hex[:12]}"
            session_data = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "created_at": datetime.now(UTC).isoformat(),
                "last_activity": datetime.now(UTC).isoformat(),
                "webhook_calls": [],
            }

            # Store session in Redis for 3 minutes (180 seconds)
            redis_client.setex(f"debug_session:{session_id}", 180, json.dumps(session_data))

            return {
                "session_id": session_id,
                "message": "Debug session created successfully",
                "debug_url": f"/trigger/webhook-debug/YOUR_WEBHOOK_ID?debug_session={session_id}",
            }, 201

        except Exception:
            logger.exception("Failed to create debug session")
            return {"error": "Failed to create debug session"}, 500


class DebugSessionDetailApi(Resource):
    """Debug session detail API."""

    @setup_required
    @login_required
    @account_initialization_required
    def get(self, session_id: str):
        """Get debug session status and recent webhook calls."""
        try:
            session_data = redis_client.get(f"debug_session:{session_id}")
            if not session_data:
                return {"error": "Debug session not found"}, 404

            # Parse session data
            session = json.loads(session_data.decode("utf-8"))

            # Verify tenant ownership
            if session["tenant_id"] != current_user.current_tenant_id:
                return {"error": "Access denied"}, 403

            return {
                "session_id": session["session_id"],
                "tenant_id": session["tenant_id"],
                "created_at": session["created_at"],
                "last_activity": session["last_activity"],
                "webhook_calls_count": len(session["webhook_calls"]),
                "recent_webhook_calls": session["webhook_calls"][-5:],  # Return only last 5 calls
            }, 200

        except Exception:
            logger.exception("Failed to get debug session")
            return {"error": "Failed to get debug session"}, 500

    @setup_required
    @login_required
    @account_initialization_required
    def delete(self, session_id: str):
        """End a debug session."""
        try:
            # Verify tenant ownership before deletion
            session_data = redis_client.get(f"debug_session:{session_id}")
            if session_data:
                session = json.loads(session_data.decode("utf-8"))
                if session["tenant_id"] != current_user.current_tenant_id:
                    return {"error": "Access denied"}, 403

            redis_client.delete(f"debug_session:{session_id}")
            return {"message": "Debug session ended successfully"}, 200

        except Exception:
            logger.exception("Failed to end debug session")
            return {"error": "Failed to end debug session"}, 500


def _add_to_debug_session(session_id: str, debug_info: dict):
    """Add debug info to session history."""
    try:
        session_data = redis_client.get(f"debug_session:{session_id}")
        if session_data:
            session = json.loads(session_data.decode("utf-8"))

            # Add webhook call to session history
            session["webhook_calls"].append(debug_info)

            # Keep only last 20 calls
            if len(session["webhook_calls"]) > 20:
                session["webhook_calls"] = session["webhook_calls"][-20:]

            # Update session
            session["last_activity"] = datetime.now(UTC).isoformat()
            redis_client.setex(f"debug_session:{session_id}", 86400, json.dumps(session))

    except Exception:
        logger.exception("Failed to add to debug session")
