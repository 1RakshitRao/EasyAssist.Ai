"""Onboarding task templates and generation."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Dict, List

from app.onboarding import store

UNIVERSAL_TASKS: List[Dict[str, Any]] = [
    {
        "task_key": "setup_mfa",
        "title": "Set up Multi-Factor Authentication",
        "description": "Configure Microsoft Authenticator and register recovery methods",
        "category": "identity",
        "link_url": "https://aka.ms/mfasetup",
        "sort_order": 1,
    },
    {
        "task_key": "reset_password",
        "title": "Reset your temporary password",
        "description": "Change your temporary password to a secure personal password",
        "category": "identity",
        "link_url": "https://account.activedirectory.windowsazure.com",
        "sort_order": 2,
    },
    {
        "task_key": "payroll_account",
        "title": "Create your ADP payroll account",
        "description": "Set up your ADP account to receive your paycheck",
        "category": "payroll",
        "link_url": "https://workforcenow.adp.com",
        "sort_order": 3,
    },
    {
        "task_key": "tax_forms",
        "title": "Complete your tax forms (W-4)",
        "description": "Submit your federal and state tax withholding forms",
        "category": "payroll",
        "sort_order": 4,
    },
    {
        "task_key": "direct_deposit",
        "title": "Set up direct deposit",
        "description": "Add your bank account details for payroll",
        "category": "payroll",
        "sort_order": 5,
    },
    {
        "task_key": "i9_verification",
        "title": "Complete I-9 employment verification",
        "description": "Upload your identity documents for employment eligibility",
        "category": "documents",
        "sort_order": 6,
    },
    {
        "task_key": "benefits_enrollment",
        "title": "Enroll in company benefits",
        "description": "Choose your health insurance, dental, and vision plans",
        "category": "benefits",
        "sort_order": 7,
    },
]

DEPARTMENT_TASKS: Dict[str, List[Dict[str, Any]]] = {
    "engineering": [
        {
            "task_key": "github_access",
            "title": "Activate GitHub Enterprise access",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "jira_access",
            "title": "Set up Jira access",
            "category": "apps",
            "sort_order": 9,
        },
        {
            "task_key": "vpn_setup",
            "title": "Install and configure VPN",
            "category": "apps",
            "sort_order": 10,
        },
        {
            "task_key": "slack_setup",
            "title": "Join company Slack workspace",
            "category": "apps",
            "sort_order": 11,
        },
    ],
    "data": [
        {
            "task_key": "snowflake_access",
            "title": "Request Snowflake access",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "databricks_access",
            "title": "Set up Databricks account",
            "category": "apps",
            "sort_order": 9,
        },
        {
            "task_key": "aws_console",
            "title": "Configure AWS Console access",
            "category": "apps",
            "sort_order": 10,
        },
    ],
    "hr": [
        {
            "task_key": "workday_access",
            "title": "Activate Workday account",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "adp_admin",
            "title": "Set up ADP admin access",
            "category": "apps",
            "sort_order": 9,
        },
    ],
    "sales": [
        {
            "task_key": "salesforce_access",
            "title": "Activate Salesforce account",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "linkedin_sales",
            "title": "Set up LinkedIn Sales Navigator",
            "category": "apps",
            "sort_order": 9,
        },
    ],
    "compliance": [
        {
            "task_key": "workday_access",
            "title": "Activate Workday account",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "compliance_portal",
            "title": "Access compliance training portal",
            "category": "apps",
            "sort_order": 9,
        },
    ],
    "legal": [
        {
            "task_key": "docusign_access",
            "title": "Set up DocuSign account",
            "category": "apps",
            "sort_order": 8,
        },
        {
            "task_key": "legal_portal",
            "title": "Access legal document management",
            "category": "apps",
            "sort_order": 9,
        },
    ],
}


def expected_task_count(department: str) -> int:
    dept = (department or "").strip().lower()
    return len(UNIVERSAL_TASKS) + len(DEPARTMENT_TASKS.get(dept, []))


def _due_date(joining_date: str) -> str:
    joined = date.fromisoformat(joining_date)
    return (joined + timedelta(days=7)).isoformat()


def _template_rows(employee: Dict[str, Any]) -> List[Dict[str, Any]]:
    email = employee["email"]
    dept = employee["department"]
    due = _due_date(employee["joining_date"])
    rows: List[Dict[str, Any]] = []

    for tpl in UNIVERSAL_TASKS:
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "employee_email": email,
                "task_key": tpl["task_key"],
                "task_title": tpl["title"],
                "task_description": tpl.get("description"),
                "category": tpl["category"],
                "status": "pending",
                "due_date": due,
                "link_url": tpl.get("link_url"),
                "department_specific": False,
                "sort_order": tpl.get("sort_order", 0),
            }
        )

    for tpl in DEPARTMENT_TASKS.get(dept, []):
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "employee_email": email,
                "task_key": tpl["task_key"],
                "task_title": tpl["title"],
                "task_description": tpl.get("description"),
                "category": tpl["category"],
                "status": "pending",
                "due_date": due,
                "link_url": tpl.get("link_url"),
                "department_specific": True,
                "sort_order": tpl.get("sort_order", 0),
            }
        )
    return rows


def generate_tasks(employee: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Insert onboarding tasks for a new employee (idempotent)."""
    email = employee["email"]
    existing = store.count_tasks_for_employee(email)
    if existing:
        return store.get_tasks(email)
    rows = _template_rows(employee)
    store.insert_tasks(rows)
    return rows
