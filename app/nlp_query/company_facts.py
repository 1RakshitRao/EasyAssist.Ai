"""Company facts CRUD + seed data for employee NLP queries."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()

SEED_CATEGORIES = (
    "clients",
    "services",
    "locations",
    "products",
    "team",
    "partnerships",
)

FACT_CATEGORIES = SEED_CATEGORIES


def _fact(
    category: str,
    name: str,
    *,
    description: str,
    detail_1: str,
    detail_2: str,
    active: int = 1,
    **attrs: Any,
) -> Dict[str, Any]:
    return {
        "category": category,
        "name": name,
        "description": description,
        "detail_1": detail_1,
        "detail_2": detail_2,
        "active": active,
        "details": json.dumps(attrs, ensure_ascii=False),
    }


_SEED: List[Dict[str, Any]] = [
    # —— Clients (10) ——
    _fact(
        "clients",
        "Acme Corporation",
        description="Manufacturing enterprise client in North America",
        detail_1="Tier Enterprise · 12,000 employees · since 2019",
        detail_2="SOC2 · revenue $10M+ · longest running enterprise client",
        industry="Manufacturing",
        tier="Enterprise",
        region="North America",
        employee_count=12000,
        since_year=2019,
        compliance_tags="SOC2",
        sensitivity="Standard",
        revenue_band="$10M+",
        status="active",
        notes="Longest running enterprise client",
    ),
    _fact(
        "clients",
        "Global Tech Partners",
        description="Financial services strategic client in North America",
        detail_1="Tier Strategic · 4,500 employees · since 2021",
        detail_2="SOC2,PCI · High sensitivity · expanding to EMEA in Q3",
        industry="Financial Services",
        tier="Strategic",
        region="North America",
        employee_count=4500,
        since_year=2021,
        compliance_tags="SOC2,PCI",
        sensitivity="High",
        revenue_band="$5M-$10M",
        status="active",
        notes="Expanding to EMEA in Q3",
    ),
    _fact(
        "clients",
        "Meridian Group",
        description="Healthcare enterprise client requiring compliance-sensitive handling",
        detail_1="Tier Enterprise · 8,200 employees · since 2020",
        detail_2="SOC2,HIPAA · quarterly compliance review required",
        industry="Healthcare",
        tier="Enterprise",
        region="North America",
        employee_count=8200,
        since_year=2020,
        compliance_tags="SOC2,HIPAA",
        sensitivity="Compliance-sensitive",
        revenue_band="$10M+",
        status="active",
        notes="Requires quarterly compliance review",
    ),
    _fact(
        "clients",
        "Vertex Solutions",
        description="EMEA technology SaaS client on a standard tier",
        detail_1="Tier Standard · 900 employees · since 2022 · region EMEA",
        detail_2="GDPR · revenue $1M-$5M · fast growing SaaS startup",
        industry="Technology",
        tier="Standard",
        region="EMEA",
        employee_count=900,
        since_year=2022,
        compliance_tags="GDPR",
        sensitivity="Standard",
        revenue_band="$1M-$5M",
        status="active",
        notes="Fast growing SaaS startup",
    ),
    _fact(
        "clients",
        "Bluewater Capital",
        description="Finance strategic client and Ampcus's oldest account",
        detail_1="Tier Strategic · 2,200 employees · since 2018",
        detail_2="SOC2,PCI,SEC · High sensitivity · renewal due Q4",
        industry="Finance",
        tier="Strategic",
        region="North America",
        employee_count=2200,
        since_year=2018,
        compliance_tags="SOC2,PCI,SEC",
        sensitivity="High",
        revenue_band="$5M-$10M",
        status="active",
        notes="Oldest client — renewal due Q4",
    ),
    _fact(
        "clients",
        "Apex Retail Group",
        description="APAC retail client currently in onboarding",
        detail_1="Tier Standard · 3,100 employees · since 2023 · region APAC",
        detail_2="PCI · revenue $1M-$5M · new client onboarding phase",
        industry="Retail",
        tier="Standard",
        region="APAC",
        employee_count=3100,
        since_year=2023,
        compliance_tags="PCI",
        sensitivity="Standard",
        revenue_band="$1M-$5M",
        status="active",
        notes="New client — onboarding phase",
    ),
    _fact(
        "clients",
        "Northstar Insurance",
        description="Insurance enterprise client with multiple compliance frameworks",
        detail_1="Tier Enterprise · 6,700 employees · since 2020",
        detail_2="SOC2,HIPAA,SEC · Compliance-sensitive · revenue $10M+",
        industry="Insurance",
        tier="Enterprise",
        region="North America",
        employee_count=6700,
        since_year=2020,
        compliance_tags="SOC2,HIPAA,SEC",
        sensitivity="Compliance-sensitive",
        revenue_band="$10M+",
        status="active",
        notes="Three compliance frameworks active",
    ),
    _fact(
        "clients",
        "Orion Energy",
        description="EMEA energy client focused on renewables",
        detail_1="Tier Standard · 1,800 employees · since 2022 · region EMEA",
        detail_2="GDPR,ISO27001 · revenue $1M-$5M · renewable energy focus",
        industry="Energy",
        tier="Standard",
        region="EMEA",
        employee_count=1800,
        since_year=2022,
        compliance_tags="GDPR,ISO27001",
        sensitivity="Standard",
        revenue_band="$1M-$5M",
        status="active",
        notes="Renewable energy focus",
    ),
    _fact(
        "clients",
        "Cascade Pharma",
        description="Pharmaceuticals strategic client with FDA obligations",
        detail_1="Tier Strategic · 5,500 employees · since 2021",
        detail_2="SOC2,HIPAA,FDA · Compliance-sensitive · FDA audit scheduled Q2",
        industry="Pharmaceuticals",
        tier="Strategic",
        region="North America",
        employee_count=5500,
        since_year=2021,
        compliance_tags="SOC2,HIPAA,FDA",
        sensitivity="Compliance-sensitive",
        revenue_band="$5M-$10M",
        status="active",
        notes="FDA audit scheduled Q2",
    ),
    _fact(
        "clients",
        "Redwood Logistics",
        description="APAC logistics client with contract under renegotiation",
        detail_1="Tier Standard · 2,800 employees · since 2023 · region APAC",
        detail_2="ISO27001 · inactive · contract under renegotiation",
        active=0,
        industry="Logistics",
        tier="Standard",
        region="APAC",
        employee_count=2800,
        since_year=2023,
        compliance_tags="ISO27001",
        sensitivity="Standard",
        revenue_band="$1M-$5M",
        status="inactive",
        notes="Contract under renegotiation",
    ),
    # —— Services (7) ——
    _fact(
        "services",
        "AI Helpdesk Platform",
        description="Internal AI-powered employee support across HR, IT, Compliance, and Legal",
        detail_1="Internal · 24/7 · launched 2024 · ~4,200 monthly queries",
        detail_2="Users: all employees · compliance SOC2 · status active",
        type="Internal",
        departments="HR,IT,Compliance,Legal",
        availability="24/7",
        compliance_tags="SOC2",
        users="All employees",
        launched_year=2024,
        monthly_queries=4200,
        status="active",
    ),
    _fact(
        "services",
        "Compliance Advisory",
        description="External regulatory and policy advisory for enterprise clients",
        detail_1="External · business hours · Compliance,Legal · launched 2020",
        detail_2="SOC2,PCI,GDPR · ~310 monthly queries · status active",
        type="External",
        departments="Compliance,Legal",
        availability="Business hours",
        compliance_tags="SOC2,PCI,GDPR",
        users="Enterprise clients",
        launched_year=2020,
        monthly_queries=310,
        status="active",
    ),
    _fact(
        "services",
        "Data Privacy Consulting",
        description="External privacy consulting for healthcare and finance clients",
        detail_1="External · Legal,Compliance · business hours · launched 2021",
        detail_2="GDPR,HIPAA · ~185 monthly queries · status active",
        type="External",
        departments="Legal,Compliance",
        availability="Business hours",
        compliance_tags="GDPR,HIPAA",
        users="Healthcare and Finance clients",
        launched_year=2021,
        monthly_queries=185,
        status="active",
    ),
    _fact(
        "services",
        "IT Managed Services",
        description="External 24/7 IT managed services for strategic clients",
        detail_1="External · IT · 24/7 · launched 2019 · ~620 monthly queries",
        detail_2="SOC2,ISO27001 · users: strategic clients · status active",
        type="External",
        departments="IT",
        availability="24/7",
        compliance_tags="SOC2,ISO27001",
        users="Strategic clients",
        launched_year=2019,
        monthly_queries=620,
        status="active",
    ),
    _fact(
        "services",
        "HR Policy Advisory",
        description="External HR policy advisory for enterprise clients",
        detail_1="External · HR · business hours · launched 2022 · ~140 monthly queries",
        detail_2="SOC2 · status active",
        type="External",
        departments="HR",
        availability="Business hours",
        compliance_tags="SOC2",
        users="Enterprise clients",
        launched_year=2022,
        monthly_queries=140,
        status="active",
    ),
    _fact(
        "services",
        "Security Assessment",
        description="External security assessments for all client tiers",
        detail_1="External · IT,Compliance · by appointment · launched 2023",
        detail_2="SOC2,ISO27001,PCI · ~90 monthly queries · status active",
        type="External",
        departments="IT,Compliance",
        availability="By appointment",
        compliance_tags="SOC2,ISO27001,PCI",
        users="All client tiers",
        launched_year=2023,
        monthly_queries=90,
        status="active",
    ),
    _fact(
        "services",
        "AI Strategy Consulting",
        description="External AI strategy consulting for enterprise and strategic clients",
        detail_1="External · Product,Engineering · business hours · launched 2024",
        detail_2="SOC2 · ~55 monthly queries · status beta",
        type="External",
        departments="Product,Engineering",
        availability="Business hours",
        compliance_tags="SOC2",
        users="Enterprise and Strategic clients",
        launched_year=2024,
        monthly_queries=55,
        status="beta",
    ),
    # —— Locations (6) ——
    _fact(
        "locations",
        "New York HQ",
        description="Ampcus headquarters in New York, USA",
        detail_1="Headquarters · 350 employees · EST · opened 2015 · 28,000 sq ft",
        detail_2="Departments: Engineering, Product, Legal, HR",
        type="Headquarters",
        city="New York",
        state="NY",
        country="USA",
        timezone="EST",
        employee_count=350,
        departments="Engineering,Product,Legal,HR",
        opened_year=2015,
        sq_footage=28000,
        status="active",
    ),
    _fact(
        "locations",
        "Austin Delivery Center",
        description="US delivery and customer success hub in Austin, Texas",
        detail_1="Delivery center · 120 employees · CST · opened 2021 · 9,500 sq ft",
        detail_2="Departments: Customer Success, Operations",
        type="Delivery center",
        city="Austin",
        state="TX",
        country="USA",
        timezone="CST",
        employee_count=120,
        departments="Customer Success,Operations",
        opened_year=2021,
        sq_footage=9500,
        status="active",
    ),
    _fact(
        "locations",
        "London Office",
        description="UK regional office in London",
        detail_1="Regional office · 65 employees · GMT · opened 2022 · 4,200 sq ft",
        detail_2="Departments: Sales, Compliance, Legal",
        type="Regional office",
        city="London",
        state="England",
        country="UK",
        timezone="GMT",
        employee_count=65,
        departments="Sales,Compliance,Legal",
        opened_year=2022,
        sq_footage=4200,
        status="active",
    ),
    _fact(
        "locations",
        "Bangalore Tech Hub",
        description="Engineering hub in Bangalore, India",
        detail_1="Engineering hub · 210 employees · IST · opened 2023 · 12,000 sq ft",
        detail_2="Departments: Engineering, QA, DevOps",
        type="Engineering hub",
        city="Bangalore",
        state="Karnataka",
        country="India",
        timezone="IST",
        employee_count=210,
        departments="Engineering,QA,DevOps",
        opened_year=2023,
        sq_footage=12000,
        status="active",
    ),
    _fact(
        "locations",
        "Toronto Office",
        description="Canada regional office in Toronto",
        detail_1="Regional office · 45 employees · EST · opened 2023 · 2,800 sq ft",
        detail_2="Departments: Sales, HR",
        type="Regional office",
        city="Toronto",
        state="Ontario",
        country="Canada",
        timezone="EST",
        employee_count=45,
        departments="Sales,HR",
        opened_year=2023,
        sq_footage=2800,
        status="active",
    ),
    _fact(
        "locations",
        "Singapore Hub",
        description="APAC hub in Singapore",
        detail_1="APAC hub · 38 employees · SGT · opened 2024 · 2,100 sq ft",
        detail_2="Departments: Sales, Customer Success",
        type="APAC hub",
        city="Singapore",
        state="Singapore",
        country="Singapore",
        timezone="SGT",
        employee_count=38,
        departments="Sales,Customer Success",
        opened_year=2024,
        sq_footage=2100,
        status="active",
    ),
    # —— Products (6) ——
    _fact(
        "products",
        "Ampcus Knowledge Base",
        description="Internal departmental policy and procedure library",
        detail_1="Internal platform · Engineering · v2.1 · 745 monthly users",
        detail_2="Departments HR,IT,Compliance,Legal · access: all employees",
        type="Internal platform",
        owner="Engineering",
        departments="HR,IT,Compliance,Legal",
        users="All employees",
        version="2.1",
        access="All employees",
        monthly_users=745,
        status="active",
    ),
    _fact(
        "products",
        "Ops Health Dashboard",
        description="Internal ticket and SLA command center for admins",
        detail_1="Internal tooling · Operations · v1.4 · 12 monthly users",
        detail_2="Access: admin only · departments Operations, Engineering",
        type="Internal tooling",
        owner="Operations",
        departments="Operations,Engineering",
        users="Admin only",
        version="1.4",
        access="Admin only",
        monthly_users=12,
        status="active",
    ),
    _fact(
        "products",
        "Client Portal",
        description="External platform for enterprise client accounts",
        detail_1="External platform · Product · v3.0 · 2,300 monthly users",
        detail_2="Customer Success, Sales · access: client accounts",
        type="External platform",
        owner="Product",
        departments="Customer Success,Sales",
        users="Enterprise clients",
        version="3.0",
        access="Client accounts",
        monthly_users=2300,
        status="active",
    ),
    _fact(
        "products",
        "Compliance Tracker",
        description="Internal compliance tracking platform",
        detail_1="Internal platform · Compliance · v1.0 · 18 monthly users",
        detail_2="Access: restricted · Compliance and Legal",
        type="Internal platform",
        owner="Compliance",
        departments="Compliance,Legal",
        users="Compliance team",
        version="1.0",
        access="Restricted",
        monthly_users=18,
        status="active",
    ),
    _fact(
        "products",
        "AI Query Engine",
        description="Internal beta AI query platform for admins and employees",
        detail_1="Internal platform · Engineering · v0.9 · 34 monthly users",
        detail_2="Beta — internal only · departments: all",
        type="Internal platform",
        owner="Engineering",
        departments="All",
        users="Admin and employees",
        version="0.9",
        access="Beta — internal only",
        monthly_users=34,
        status="beta",
    ),
    _fact(
        "products",
        "Field Service App",
        description="Mobile application for on-site operations teams",
        detail_1="Mobile application · Product · v1.2 · 89 monthly users",
        detail_2="Access: operations staff · Customer Success, Operations",
        type="Mobile application",
        owner="Product",
        departments="Customer Success,Operations",
        users="On-site teams",
        version="1.2",
        access="Operations staff",
        monthly_users=89,
        status="active",
    ),
    # —— Team (6) ——
    _fact(
        "team",
        "Sarah Chen",
        description="Chief Technology Officer leading Engineering from New York HQ",
        detail_1="CTO · Engineering · New York HQ · joined 2017",
        detail_2="Expertise: AI, Cloud Architecture, Security",
        title="Chief Technology Officer",
        department="Engineering",
        location="New York HQ",
        expertise="AI,Cloud Architecture,Security",
        joined_year=2017,
        status="active",
    ),
    _fact(
        "team",
        "Marcus Williams",
        description="Head of Compliance based at New York HQ",
        detail_1="Head of Compliance · Compliance · New York HQ · joined 2019",
        detail_2="Expertise: GDPR, SOC2, HIPAA, PCI",
        title="Head of Compliance",
        department="Compliance",
        location="New York HQ",
        expertise="GDPR,SOC2,HIPAA,PCI",
        joined_year=2019,
        status="active",
    ),
    _fact(
        "team",
        "Priya Nair",
        description="VP Engineering based at Bangalore Tech Hub",
        detail_1="VP Engineering · Engineering · Bangalore Tech Hub · joined 2023",
        detail_2="Expertise: Backend, AI, Platform",
        title="VP Engineering",
        department="Engineering",
        location="Bangalore Tech Hub",
        expertise="Backend,AI,Platform",
        joined_year=2023,
        status="active",
    ),
    _fact(
        "team",
        "David Osei",
        description="Head of Legal based at London Office",
        detail_1="Head of Legal · Legal · London Office · joined 2022",
        detail_2="Expertise: Employment Law, Contracts, IP",
        title="Head of Legal",
        department="Legal",
        location="London Office",
        expertise="Employment Law,Contracts,IP",
        joined_year=2022,
        status="active",
    ),
    _fact(
        "team",
        "Rachel Torres",
        description="Head of HR based at New York HQ",
        detail_1="Head of HR · HR · New York HQ · joined 2020",
        detail_2="Expertise: Policy, Talent, L&D",
        title="Head of HR",
        department="HR",
        location="New York HQ",
        expertise="Policy,Talent,L&D",
        joined_year=2020,
        status="active",
    ),
    _fact(
        "team",
        "James Kwon",
        description="Head of Customer Success based at Austin Delivery Center",
        detail_1="Head of Customer Success · Austin Delivery Center · joined 2021",
        detail_2="Expertise: Client Relations, Onboarding, SLA",
        title="Head of Customer Success",
        department="Customer Success",
        location="Austin Delivery Center",
        expertise="Client Relations,Onboarding,SLA",
        joined_year=2021,
        status="active",
    ),
    # —— Partnerships (5) ——
    _fact(
        "partnerships",
        "Anthropic",
        description="Technology vendor providing Claude API for Ampcus AI products",
        detail_1="Technology vendor · Claude API · Enterprise tier · since 2024",
        detail_2="Used for AI Helpdesk Platform, AI Query Engine, AI Strategy Consulting",
        type="Technology vendor",
        product="Claude API",
        used_for="AI Helpdesk Platform,AI Query Engine,AI Strategy Consulting",
        contract_tier="Enterprise",
        since_year=2024,
        compliance_tags="SOC2",
        status="active",
    ),
    _fact(
        "partnerships",
        "AWS",
        description="Cloud infrastructure partner for Ampcus platform hosting",
        detail_1="Cloud infrastructure · EC2,S3,RDS,Lambda · Enterprise · since 2019",
        detail_2="Used for all platform infrastructure · SOC2,ISO27001,HIPAA",
        type="Cloud infrastructure",
        product="EC2,S3,RDS,Lambda",
        used_for="All platform infrastructure",
        contract_tier="Enterprise",
        since_year=2019,
        compliance_tags="SOC2,ISO27001,HIPAA",
        status="active",
    ),
    _fact(
        "partnerships",
        "Salesforce",
        description="CRM platform partner for sales and client management",
        detail_1="CRM platform · Sales Cloud, Service Cloud · Business · since 2020",
        detail_2="Used for client management and sales pipeline · SOC2",
        type="CRM platform",
        product="Sales Cloud,Service Cloud",
        used_for="Client management,Sales pipeline",
        contract_tier="Business",
        since_year=2020,
        compliance_tags="SOC2",
        status="active",
    ),
    _fact(
        "partnerships",
        "Okta",
        description="Identity provider for employee and client portal authentication",
        detail_1="Identity provider · SSO,MFA,Directory · Business · since 2021",
        detail_2="Used for employee authentication and client portal access · SOC2,FedRAMP",
        type="Identity provider",
        product="SSO,MFA,Directory",
        used_for="Employee authentication,Client portal access",
        contract_tier="Business",
        since_year=2021,
        compliance_tags="SOC2,FedRAMP",
        status="active",
    ),
    _fact(
        "partnerships",
        "ServiceNow",
        description="IT service management partner for IT and HR workflows",
        detail_1="ITSM · ITSM, HR Service Delivery · Enterprise · since 2022",
        detail_2="Used for IT ticketing and HR requests · SOC2,ISO27001",
        type="IT service management",
        product="ITSM,HR Service Delivery",
        used_for="IT ticketing,HR requests",
        contract_tier="Enterprise",
        since_year=2022,
        compliance_tags="SOC2,ISO27001",
        status="active",
    ),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_details_column(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(company_facts)").fetchall()}
    if "details" not in cols:
        conn.execute("ALTER TABLE company_facts ADD COLUMN details TEXT")


def seed_company_facts_if_empty() -> int:
    """Upsert the official Ampcus company-facts seed (40 rows across 6 categories)."""
    init_audit_db()
    with _lock:
        with connect() as conn:
            _ensure_details_column(conn)
            team_n = conn.execute(
                "SELECT COUNT(*) AS n FROM company_facts WHERE category = 'team'"
            ).fetchone()["n"]
            total = conn.execute("SELECT COUNT(*) AS n FROM company_facts").fetchone()["n"]
            # Refresh when empty, missing new categories, or still on the old 9-row seed
            if int(total or 0) > 0 and int(team_n or 0) > 0 and int(total or 0) >= len(_SEED) - 1:
                return 0

            placeholders = ",".join("?" for _ in SEED_CATEGORIES)
            conn.execute(
                f"DELETE FROM company_facts WHERE category IN ({placeholders})",
                SEED_CATEGORIES,
            )
            now = _now()
            for item in _SEED:
                conn.execute(
                    """
                    INSERT INTO company_facts (
                        id, category, name, description, detail_1, detail_2,
                        active, created_at, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        item["category"],
                        item["name"],
                        item["description"],
                        item["detail_1"],
                        item["detail_2"],
                        int(item.get("active", 1)),
                        now,
                        item.get("details") or "{}",
                    ),
                )
            conn.commit()
    logger.info("Seeded company_facts rows=%d categories=%s", len(_SEED), SEED_CATEGORIES)
    return len(_SEED)


def list_facts(category: str | None = None, active_only: bool = True) -> List[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        _ensure_details_column(conn)
        sql = "SELECT * FROM company_facts WHERE 1=1"
        params: list[Any] = []
        if active_only:
            sql += " AND active = 1"
        if category:
            sql += " AND category = ?"
            params.append(category.strip().lower())
        sql += " ORDER BY category, name"
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def create_fact(
    *,
    category: str,
    name: str,
    description: str = "",
    detail_1: str = "",
    detail_2: str = "",
    active: bool = True,
    details: str | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    cat = (category or "").strip().lower()
    nm = (name or "").strip()
    if not cat or not nm:
        raise ValueError("category and name are required")
    if cat not in FACT_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(FACT_CATEGORIES)}")
    if isinstance(details, dict):
        details_json = json.dumps(details, ensure_ascii=False)
    else:
        details_json = details or "{}"
    fact_id = str(uuid.uuid4())
    now = _now()
    with _lock:
        with connect() as conn:
            _ensure_details_column(conn)
            conn.execute(
                """
                INSERT INTO company_facts (
                    id, category, name, description, detail_1, detail_2,
                    active, created_at, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    cat,
                    nm,
                    description or "",
                    detail_1 or "",
                    detail_2 or "",
                    1 if active else 0,
                    now,
                    details_json,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM company_facts WHERE id = ?", (fact_id,)
            ).fetchone()
    return dict(row)


def delete_fact(fact_id: str) -> bool:
    init_audit_db()
    with _lock:
        with connect() as conn:
            cur = conn.execute("DELETE FROM company_facts WHERE id = ?", (fact_id,))
            conn.commit()
            return cur.rowcount > 0


def get_fact(fact_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        _ensure_details_column(conn)
        row = conn.execute(
            "SELECT * FROM company_facts WHERE id = ?", (fact_id,)
        ).fetchone()
    return dict(row) if row else None
