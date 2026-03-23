from pathlib import Path


ADMIN_DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def test_admin_dashboard_includes_assistant_panel_and_endpoint_hook():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "admin-assistant-panel" in content
    assert 'id="admin-assistant-input"' in content
    assert "fetch('/api/admin/assistant'" in content
    assert "const adminAssistantActionHandlers = {" in content
    assert "askAdminAssistant('Give me a dashboard summary')" in content


def test_admin_dashboard_assistant_maps_main_dashboard_actions():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    for function_name in (
        "refreshAllData",
        "validateAllCustomers",
        "processAllPipelines",
        "allocateAllSavings",
        "generateMissingBilling",
        "approveAllPending",
        "loadAIInsights",
        "reconcileBalanceSheet",
        "executeBillAll",
        "cleanupDemoData",
    ):
        assert f"{function_name}()" in content


def test_admin_dashboard_assistant_includes_workflow_state_hooks():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "id=\"admin-assistant-workflow\"" in content
    assert "ADMIN_ASSISTANT_STORAGE_KEY" in content
    assert "loadAdminAssistantWorkflowState" in content
    assert "saveAdminAssistantWorkflowState" in content
    assert "syncAdminAssistantWorkflowState" in content
    assert "loadAdminAssistantWorkflowFromBackend" in content
    assert "executeAdminAssistantWorkflow" in content
    assert "current_step_index" in content


def test_admin_dashboard_assistant_uses_structured_action_results():
    content = ADMIN_DASHBOARD_PATH.read_text(encoding="utf-8")

    assert "function buildAssistantActionResult" in content
    assert "return buildAssistantActionResult({" in content
    assert "const result = await executeAdminAssistantAction(step.id);" in content
    assert "window.alert = (message) =>" not in content
    assert "window.confirm = (message) =>" not in content
