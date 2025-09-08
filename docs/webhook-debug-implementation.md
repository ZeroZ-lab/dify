# Webhook Debug Implementation

## Overview

This document describes the implementation of webhook debug functionality for the Dify platform. The debug system allows developers to monitor webhook requests in real-time and trigger workflow execution for debugging purposes.

## Important Notes

- **Session Duration**: Debug sessions automatically expire after 3 minutes
- **No Heartbeat**: Sessions do not require heartbeat maintenance
- **Auto-cleanup**: Expired sessions are automatically cleaned up by Redis
- **Manual Termination**: Sessions can be manually ended via DELETE API

## Architecture

### Components

1. **Console Debug Module** (`/api/controllers/console/debug.py`)
   - Manages debug sessions
   - Provides REST API for session lifecycle
   - Handles heartbeat and cleanup

2. **Webhook Debug Endpoint** (`/api/controllers/trigger/webhook.py`)
   - Receives webhook requests in debug mode
   - Triggers workflow execution
   - Returns debug information including `workflow_run_id`

3. **Webhook Service** (`/api/services/webhook_service.py`)
   - Core webhook processing logic
   - Supports debug mode with workflow run tracking
   - Returns `workflow_run_id` for debug sessions

### Data Flow

```
Frontend → Console API → Debug Session (Redis)
                      ↓
Webhook Request → Trigger API → Webhook Service → Workflow Execution
                      ↓
               Debug Info → Redis Session → Frontend (Polling)
```

## API Endpoints

### Console Debug API

#### Create Debug Session
- **POST** `/console/api/debug/sessions`
- **Request**: `{}` (empty body, tenant_id is obtained from authentication)
- **Response**: 
  ```json
  {
    "session_id": "debug_session_abc123",
    "message": "Debug session created successfully",
    "debug_url": "/trigger/webhook-debug/YOUR_WEBHOOK_ID?debug_session=debug_session_abc123"
  }
  ```

#### Get Debug Session
- **GET** `/console/api/debug/sessions/{session_id}`
- **Response**:
  ```json
  {
    "session_id": "debug_session_abc123",
    "tenant_id": "tenant_123",
    "created_at": "2024-01-01T10:00:00Z",
    "last_activity": "2024-01-01T10:05:00Z",
    "webhook_calls_count": 3,
    "recent_webhook_calls": [
      {
        "webhook_id": "webhook_456",
        "debug_session_id": "debug_session_abc123",
        "tenant_id": "tenant_123",
        "app_id": "app_789",
        "received_at": "2024-01-01T10:05:00Z",
        "request": {
          "method": "POST",
          "headers": {},
          "query_params": {},
          "body": {}
        },
        "validation": {
          "valid": true
        },
        "workflow_run_id": "run_123"
      }
    ]
  }
  ```


#### End Debug Session
- **DELETE** `/console/api/debug/sessions/{session_id}`
- **Response**: `{ "message": "Debug session ended successfully" }`

### Webhook Debug Endpoint

#### Debug Webhook Handler
- **All Methods** `/trigger/webhook-debug/{webhook_id}`
- **Query Parameters**: `debug_session` (optional)
- **Headers**: `X-Debug-Session` (optional)
- **Response**:
  ```json
  {
    "status": "success",
    "webhook_id": "webhook_456",
    "debug_session_id": "debug_session_abc123",
    "debug_key": "webhook_debug:def456",
    "workflow_run_id": "run_123",
    "message": "Debug webhook processed successfully",
    "workflow_id": "workflow_789",
    "node_id": "node_123",
    "received_at": "2024-01-01T10:05:00Z",
    "request_summary": {
      "method": "POST",
      "content_type": "application/json",
      "body_size": 256
    }
  }
  ```

## Frontend Implementation

### 1. Start Debug Session

```javascript
async function startDebugSession() {
  const response = await fetch('/console/api/debug/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({})  // Empty body, tenant_id is obtained from authentication
  });
  
  const { session_id, debug_url } = await response.json();
  
  return {
    sessionId: session_id,
    debugUrl: debug_url.replace('YOUR_WEBHOOK_ID', actualWebhookId)
  };
}
```

### 2. Setup Polling

```javascript
function setupDebugMonitoring(sessionId) {
  const processedRuns = new Set();
  
  // Poll for new webhook calls every 5 seconds
  const pollInterval = setInterval(async () => {
    const response = await fetch(`/console/api/debug/sessions/${sessionId}`);
    const data = await response.json();
    
    // Check for new workflow runs
    const newRuns = data.recent_webhook_calls
      .filter(call => call.workflow_run_id && !processedRuns.has(call.workflow_run_id));
    
    newRuns.forEach(call => {
      processedRuns.add(call.workflow_run_id);
      runWorkflowGraph(call.workflow_run_id);
    });
    
    // Update UI with recent calls
    updateDebugUI(data.recent_webhook_calls);
  }, 5000);
  
  return { pollInterval };
}
```

### 3. Run Workflow Graph

```javascript
async function runWorkflowGraph(workflowRunId) {
  // Implement your workflow graph rendering logic here
  console.log('Running workflow graph for:', workflowRunId);
  
  // Example:
  // - Fetch workflow execution details
  // - Update UI with execution status
  // - Show workflow node execution progress
  // - Display execution results
}
```

### 4. Cleanup

```javascript
function cleanupDebug(sessionId, pollInterval) {
  // Clear intervals
  clearInterval(pollInterval);
  
  // End debug session
  fetch(`/console/api/debug/sessions/${sessionId}`, {
    method: 'DELETE'
  });
}

// Setup cleanup on page unload
window.addEventListener('beforeunload', () => {
  cleanupDebug(sessionId, pollInterval);
});
```

## Redis Storage

### Debug Session Structure

```json
{
  "session_id": "debug_session_abc123",
  "tenant_id": "tenant_123",
  "created_at": "2024-01-01T10:00:00Z",
  "last_activity": "2024-01-01T10:05:00Z",
  "webhook_calls": [
    {
      "webhook_id": "webhook_456",
      "debug_session_id": "debug_session_abc123",
      "tenant_id": "tenant_123",
      "app_id": "app_789",
      "received_at": "2024-01-01T10:05:00Z",
      "request": {
        "method": "POST",
        "headers": {},
        "query_params": {},
        "body": {}
      },
      "validation": {
        "valid": true
      },
      "workflow_run_id": "run_123"
    }
  ]
}
```

### Redis Keys

- **Debug Session**: `debug_session:{session_id}` (expires in 3 minutes)
- **Webhook Debug**: `webhook_debug:{uuid}` (expires in 1 hour)

## Key Features

### 1. Session Management
- Debug sessions are isolated by tenant
- Automatic cleanup after 3 minutes
- Manual session termination support

### 2. Webhook Processing
- Full webhook request capture (headers, body, query params)
- Request validation against node configuration
- Workflow execution in debug mode
- Returns `workflow_run_id` for graph execution

### 3. Workflow Graph Execution
- Automatic workflow graph execution when webhook is received
- Real-time workflow progress monitoring
- Node execution status tracking
- Workflow execution completion notification

### 4. Real-time Monitoring
- Polling-based status updates (5-second intervals)
- Recent webhook calls history (last 20 calls)
- Workflow run ID tracking
- Request summary information
- Node execution progress monitoring (2-second intervals)

### 5. Error Handling
- Validation error responses
- Detailed error information in debug mode
- Graceful degradation for production vs debug

## Security Considerations

1. **Tenant Isolation**: Debug sessions are tenant-specific and validated
2. **Authentication**: All console APIs require login and account initialization
3. **Authorization**: Users can only access their own debug sessions
4. **Session Expiration**: Automatic cleanup prevents resource leaks
5. **Debug Mode**: Separate debug endpoints prevent production impact

## Performance Considerations

1. **Polling Frequency**: 5-second polling balances real-time updates with server load
2. **Redis Storage**: Efficient in-memory storage for fast access
3. **Session Limits**: Maximum 20 webhook calls per session prevents memory bloat
4. **Auto-cleanup**: 3-minute session expiration prevents resource accumulation

## Future Enhancements

1. **WebSocket Support**: Real-time updates without polling
2. **Enhanced Filtering**: Filter webhook calls by status, time range, etc.
3. **Export Functionality**: Export debug sessions for analysis
4. **Performance Metrics**: Add timing and performance data
5. **Batch Operations**: Support for testing multiple webhooks

## Testing

### Manual Testing

1. Create a debug session via console API
2. Send webhook requests to debug endpoint
3. Verify workflow execution and graph rendering
4. Check session management and cleanup

### Complete Frontend Example

```javascript
class WebhookDebugManager {
  constructor() {
    this.sessionId = null;
    this.pollInterval = null;
    this.processedRuns = new Set();
  }

  async startDebug() {
    try {
      // 1. Create debug session
      const session = await this.createDebugSession();
      this.sessionId = session.sessionId;
      
      // 2. Setup monitoring
      this.setupMonitoring();
      
      // 3. Show debug URL to user
      this.showDebugInfo(session.debugUrl);
      
      return session;
    } catch (error) {
      console.error('Failed to start debug session:', error);
      throw error;
    }
  }

  async createDebugSession() {
    const response = await fetch('/console/api/debug/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    
    if (!response.ok) {
      throw new Error('Failed to create debug session');
    }
    
    const data = await response.json();
    return {
      sessionId: data.session_id,
      debugUrl: data.debug_url.replace('YOUR_WEBHOOK_ID', this.getWebhookId())
    };
  }

  setupMonitoring() {
    // Poll for new webhook calls every 5 seconds
    this.pollInterval = setInterval(async () => {
      try {
        await this.pollDebugSession();
      } catch (error) {
        console.error('Polling failed:', error);
      }
    }, 5000);
  }

  async pollDebugSession() {
    const response = await fetch(`/console/api/debug/sessions/${this.sessionId}`);
    
    if (!response.ok) {
      if (response.status === 404) {
        this.stopDebug();
        throw new Error('Debug session expired');
      }
      throw new Error('Failed to poll debug session');
    }
    
    const data = await response.json();
    
    // Check for new workflow runs
    const newRuns = data.recent_webhook_calls
      .filter(call => call.workflow_run_id && !this.processedRuns.has(call.workflow_run_id));
    
    newRuns.forEach(call => {
      this.processedRuns.add(call.workflow_run_id);
      this.onWebhookReceived(call);
    });
    
    // Update UI
    this.updateDebugUI(data);
  }

  onWebhookReceived(call) {
    console.log('New webhook received:', call);
    
    // Trigger workflow graph execution
    if (call.workflow_run_id) {
      this.runWorkflowGraph(call.workflow_run_id, call);
    }
    
    // Show notification
    this.showNotification('Webhook received', `Method: ${call.request.method}`);
  }

  async runWorkflowGraph(workflowRunId, webhookCall) {
    try {
      console.log('Running workflow graph for:', workflowRunId);
      
      // Fetch workflow execution details
      const executionDetails = await this.fetchWorkflowExecution(workflowRunId, webhookCall);
      
      // Update UI with execution status
      this.updateWorkflowGraphUI(executionDetails);
      
      // Monitor workflow execution progress
      this.monitorWorkflowProgress(workflowRunId);
      
    } catch (error) {
      console.error('Failed to run workflow graph:', error);
      this.showNotification('Error', 'Failed to run workflow graph');
    }
  }

  async fetchWorkflowExecution(workflowRunId, webhookCall) {
    // Fetch workflow run details from the API
    const response = await fetch(`/console/api/apps/${webhookCall.app_id}/workflow-runs/${workflowRunId}`);
    
    if (!response.ok) {
      throw new Error('Failed to fetch workflow execution details');
    }
    
    const executionData = await response.json();
    
    return {
      workflowRunId,
      appId: webhookCall.app_id,
      workflowId: webhookCall.workflow_id,
      nodeId: webhookCall.node_id,
      webhookData: webhookCall.request,
      execution: executionData,
      status: 'running'
    };
  }

  updateWorkflowGraphUI(executionDetails) {
    // Update the workflow graph UI with execution details
    console.log('Updating workflow graph UI:', executionDetails);
    
    // Example UI updates:
    // - Highlight the starting node
    // - Show execution progress
    // - Display node execution status
    // - Update workflow run status
    
    // Emit event or call callback to update React components
    if (this.onWorkflowGraphUpdate) {
      this.onWorkflowGraphUpdate(executionDetails);
    }
  }

  monitorWorkflowProgress(workflowRunId) {
    // Poll for workflow execution progress
    const progressInterval = setInterval(async () => {
      try {
        const response = await fetch(`/console/api/apps/${this.currentAppId}/workflow-runs/${workflowRunId}/node-executions`);
        
        if (!response.ok) {
          clearInterval(progressInterval);
          return;
        }
        
        const data = await response.json();
        
        // Update UI with node execution progress
        this.updateNodeExecutionProgress(data.data);
        
        // Check if workflow execution is complete
        const isComplete = data.data.every(node => 
          node.status === 'success' || node.status === 'failed' || node.status === 'timeout'
        );
        
        if (isComplete) {
          clearInterval(progressInterval);
          this.showNotification('Workflow Complete', 'Workflow execution finished');
        }
        
      } catch (error) {
        console.error('Failed to monitor workflow progress:', error);
        clearInterval(progressInterval);
      }
    }, 2000); // Poll every 2 seconds
    
    // Store interval reference for cleanup
    this.progressIntervals = this.progressIntervals || new Map();
    this.progressIntervals.set(workflowRunId, progressInterval);
  }

  updateNodeExecutionProgress(nodeExecutions) {
    console.log('Updating node execution progress:', nodeExecutions);
    
    // Update UI with node execution status
    // This can be used to highlight nodes, show progress indicators, etc.
    
    // Example:
    // nodeExecutions.forEach(node => {
    //   this.updateNodeStatus(node.node_id, node.status);
    // });
  }

  showDebugInfo(debugUrl) {
    // Show debug URL to user for testing
    console.log('Debug URL:', debugUrl);
    // Update UI with debug information
  }

  updateDebugUI(data) {
    // Update UI with recent webhook calls
    console.log('Debug session data:', data);
    // Update your UI components
  }

  showNotification(title, message) {
    // Show browser notification or UI toast
    console.log(`${title}: ${message}`);
  }

  getWebhookId() {
    // Get the actual webhook ID from your application state
    return 'your-webhook-id';
  }

  stopDebug() {
    // Clear intervals
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    
    // Clear progress monitoring intervals
    if (this.progressIntervals) {
      this.progressIntervals.forEach((interval) => {
        clearInterval(interval);
      });
      this.progressIntervals.clear();
    }
    
    // End debug session
    if (this.sessionId) {
      fetch(`/console/api/debug/sessions/${this.sessionId}`, {
        method: 'DELETE'
      }).catch(error => {
        console.error('Failed to end debug session:', error);
      });
      
      this.sessionId = null;
    }
    
    // Clear processed runs
    this.processedRuns.clear();
  }
}

// Usage example:
const debugManager = new WebhookDebugManager();

// Start debug session
debugManager.startDebug().then(session => {
  console.log('Debug session started:', session);
}).catch(error => {
  console.error('Failed to start debug session:', error);
});

// Stop debug session when done
// debugManager.stopDebug();

// Auto-cleanup on page unload
window.addEventListener('beforeunload', () => {
  debugManager.stopDebug();
});
```

## Usage Example

### Complete Workflow

1. **Start Debug Session**
   ```javascript
   const debugManager = new WebhookDebugManager();
   
   // Start debug session
   const session = await debugManager.startDebug();
   console.log('Debug URL:', session.debugUrl);
   ```

2. **Send Webhook Request**
   ```bash
   curl -X POST "${session.debugUrl}" \
     -H "Content-Type: application/json" \
     -d '{"key": "value"}'
   ```

3. **Automatic Workflow Execution**
   - Webhook received → Workflow triggered → Graph executed
   - Real-time progress monitoring
   - Node execution status updates

4. **Monitor Progress**
   - Debug session shows webhook calls
   - Workflow graph highlights active nodes
   - Progress indicators show execution status

5. **View Results**
   - Complete workflow execution details
   - Node-by-node execution results
   - Error information if any occurred

### Integration with React Components

```javascript
import React, { useState, useEffect } from 'react';

const WebhookDebugPanel = ({ appId, webhookId }) => {
  const [debugManager, setDebugManager] = useState(null);
  const [isDebugging, setIsDebugging] = useState(false);
  const [webhookCalls, setWebhookCalls] = useState([]);
  const [workflowExecution, setWorkflowExecution] = useState(null);

  useEffect(() => {
    const manager = new WebhookDebugManager();
    
    // Set up callback for workflow graph updates
    manager.onWorkflowGraphUpdate = (executionDetails) => {
      setWorkflowExecution(executionDetails);
    };
    
    setDebugManager(manager);
    
    return () => {
      manager.stopDebug();
    };
  }, []);

  const startDebug = async () => {
    if (!debugManager) return;
    
    try {
      const session = await debugManager.startDebug();
      setIsDebugging(true);
      
      // Show debug URL to user
      alert(`Debug URL: ${session.debugUrl}`);
    } catch (error) {
      console.error('Failed to start debug:', error);
    }
  };

  const stopDebug = () => {
    if (debugManager) {
      debugManager.stopDebug();
      setIsDebugging(false);
      setWebhookCalls([]);
      setWorkflowExecution(null);
    }
  };

  return (
    <div>
      <div className="debug-controls">
        <button 
          onClick={isDebugging ? stopDebug : startDebug}
          className={isDebugging ? 'stop-debug' : 'start-debug'}
        >
          {isDebugging ? 'Stop Debug' : 'Start Debug'}
        </button>
      </div>
      
      {isDebugging && (
        <div className="debug-panel">
          <div className="webhook-calls">
            <h3>Recent Webhook Calls</h3>
            <ul>
              {webhookCalls.map((call, index) => (
                <li key={index}>
                  {call.request.method} - {call.received_at}
                </li>
              ))}
            </ul>
          </div>
          
          {workflowExecution && (
            <div className="workflow-execution">
              <h3>Workflow Execution</h3>
              <div className="execution-details">
                <p>Workflow ID: {workflowExecution.workflowId}</p>
                <p>Run ID: {workflowExecution.workflowRunId}</p>
                <p>Status: {workflowExecution.status}</p>
              </div>
              
              {/* Workflow graph visualization */}
              <WorkflowGraph 
                execution={workflowExecution}
                onNodeClick={(nodeId) => {
                  // Handle node click
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
```

### Automated Testing

```bash
# Run tests
uv run --project api pytest tests/api/controllers/test_debug.py
uv run --project api pytest tests/api/controllers/test_webhook.py

# Code quality
uv run --project api ruff check ./api/controllers/
uv run --project api mypy ./api/controllers/
```

## Troubleshooting

### Common Issues

1. **Session Expiration**: Ensure heartbeat is sent every 30 seconds
2. **Missing workflow_run_id**: Check that webhook processing completes successfully
3. **Permission Errors**: Verify tenant isolation and authentication
4. **Redis Connection**: Check Redis service availability

### Debug Logging

```python
import logging
logger = logging.getLogger(__name__)

# Debug session logging
logger.info("Created debug session %s for tenant %s", session_id, tenant_id)

# Webhook processing logging
logger.info("Processing debug webhook for %s, session: %s", webhook_id, debug_session_id)
```

## Conclusion

The webhook debug implementation provides a comprehensive solution for monitoring and debugging webhook requests in the Dify platform. The system combines webhook monitoring with automatic workflow graph execution, providing developers with real-time feedback and visual debugging capabilities.

### Key Benefits

1. **Seamless Integration**: Works with existing webhook infrastructure
2. **Real-time Feedback**: Immediate workflow execution upon webhook receipt
3. **Visual Debugging**: Workflow graph visualization with progress indicators
4. **Tenant Isolation**: Secure multi-tenant debugging environment
5. **Resource Efficient**: Automatic cleanup prevents resource accumulation

### Technical Highlights

- **Polling-based Architecture**: Compatible with existing infrastructure
- **Dual-layer Monitoring**: Webhook calls + workflow execution progress
- **Flexible Integration**: Easy integration with React components
- **Comprehensive API**: Full REST API for session management
- **Error Handling**: Robust error handling and validation

This implementation provides a powerful debugging tool that enhances developer productivity while maintaining system stability and security.