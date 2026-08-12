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
    "infrastructure",
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


def _team(
    name: str,
    title: str,
    department: str = "Ampcus",
    *,
    detail_2: str = "Executive leadership team",
) -> Dict[str, Any]:
    loc = "Chantilly, VA"
    return _fact(
        "team",
        name,
        description=f"{title} — {department} — based in {loc}",
        detail_1=f"{title} · {department} · {loc}",
        detail_2=detail_2,
        title=title,
        department=department,
        location=loc,
        status="active",
    )


def _location(
    city: str,
    state: str,
    *,
    office_type: str = "U.S. office",
    is_headquarters: bool = False,
    country: str = "USA",
    detail_2: str = "Listed on Ampcus Contact page",
) -> Dict[str, Any]:
    label = f"{city}, {state}"
    if is_headquarters:
        office_type = "Headquarters"
    region = "United States" if country == "USA" else country
    return _fact(
        "locations",
        label,
        description=f"Ampcus {office_type.lower()} in {label}",
        detail_1=f"{office_type} · {label} · {region}",
        detail_2=detail_2,
        type=office_type,
        city=city,
        state=state,
        country=country,
        region=region,
        is_headquarters=is_headquarters,
        status="active",
    )


def _service(
    name: str,
    description: str,
    capabilities: str,
    *,
    delivery_unit: str = "Ampcus",
) -> Dict[str, Any]:
    return _fact(
        "services",
        name,
        description=description,
        detail_1=f"Practice area · {delivery_unit}",
        detail_2=capabilities,
        type="Practice area",
        practice_area=name,
        delivery_unit=delivery_unit,
        capabilities=capabilities,
        status="active",
    )


def _partner(
    name: str,
    partner_category: str,
    *,
    description: str = "",
    alliance_level: str = "",
) -> Dict[str, Any]:
    desc = description or f"{name} — Ampcus partner ({partner_category})"
    detail_1 = f"{partner_category} · {name}"
    if alliance_level:
        detail_1 = f"{detail_1} · {alliance_level}"
    return _fact(
        "partnerships",
        name,
        description=desc,
        detail_1=detail_1,
        detail_2="Listed on Ampcus Partners page",
        type=partner_category,
        partner_category=partner_category,
        alliance_level=alliance_level or None,
        status="active",
    )


# Bump when seed content changes materially (forces DB refresh on startup).
SEED_REVISION = 5

_US_OFFICES: List[tuple[str, str, bool]] = [
    ("Chantilly", "VA", True),
    ("Atlanta", "GA", False),
    ("Charlotte", "NC", False),
    ("Chicago", "IL", False),
    ("Dallas", "TX", False),
    ("Denver", "CO", False),
    ("Detroit", "MI", False),
    ("Farmington", "CT", False),
    ("Houston", "TX", False),
    ("Jacksonville", "FL", False),
    ("Newark", "CA", False),
    ("New York", "NY", False),
    ("Owings Mills", "MD", False),
    ("Parsippany", "NJ", False),
    ("Richmond", "VA", False),
    ("San Francisco", "CA", False),
    ("Washington", "DC", False),
    ("Columbus", "OH", False),
    ("Birmingham", "AL", False),
]

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
    # —— Services (7 practice areas) ——
    _service(
        "AI, GenAI & Agentic AI",
        "Governed enterprise GenAI and agentic AI delivery",
        "Enterprise GenAI strategy, governed deployment, and agentic AI solutions",
        delivery_unit="Ampcus",
    ),
    _service(
        "Intelligent Automation",
        "AI/ML, analytics, and automation at scale",
        "AI/ML, data engineering, advanced analytics, low-code/no-code, and RPA",
        delivery_unit="Ampcus",
    ),
    _service(
        "Infrastructure Modernization",
        "Cloud, DevSecOps, and legacy transformation",
        "DevSecOps, cloud architecture and migration, legacy modernization, virtualization",
        delivery_unit="Ampcus",
    ),
    _service(
        "Cybersecurity and Risk Management",
        "Compliance, threat intelligence, and infrastructure protection",
        "Compliance and governance, threat intelligence, infrastructure protection",
        delivery_unit="Ampcus Cyber",
    ),
    _service(
        "Forensic Accounting and Fraud Investigations",
        "Insurance claims and litigation support",
        "Insurance claims, litigation support, and fraud investigations",
        delivery_unit="Ampcus Forensics",
    ),
    _service(
        "Independent Verification and Validation / Testing",
        "Software quality assurance through a Quality Center of Excellence",
        "IV&V and software testing via the Quality Center of Excellence",
        delivery_unit="Ampcus",
    ),
    _service(
        "Staffing Services",
        "Contingent labor, project staffing, and full-time placement",
        "Contingent labor, project staffing, and full-time placement via iTech and Bravens",
        delivery_unit="Ampcus",
    ),
    # —— Locations (U.S. offices + global portfolio) ——
    *[
        _location(city, state, is_headquarters=is_hq)
        for city, state, is_hq in _US_OFFICES
    ],
    _fact(
        "locations",
        "U.S. Office Network",
        description="Ampcus U.S. office footprint across 18 offices",
        detail_1="18 U.S. offices · headquarters in Chantilly, VA",
        detail_2="Full city list on Ampcus Contact page",
        type="Portfolio summary",
        region="United States",
        office_count=18,
        seed_revision=SEED_REVISION,
        status="active",
    ),
    _fact(
        "locations",
        "Global Office Network",
        description="Ampcus international office presence",
        detail_1="20 global offices worldwide",
        detail_2="Specific international addresses not listed on the public Contact page",
        type="Portfolio summary",
        region="Global",
        office_count=20,
        status="active",
    ),
    _fact(
        "locations",
        "Innovation Labs",
        description="Ampcus innovation lab locations",
        detail_1="2 innovation labs",
        detail_2="Part of Ampcus global innovation footprint",
        type="Innovation lab",
        region="Global",
        lab_count=2,
        status="active",
    ),
    _fact(
        "locations",
        "Nashik Campus",
        description="New Ampcus campus investment in Nashik, India",
        detail_1="Planned campus · Nashik, India",
        detail_2="Ongoing investment noted on Ampcus About page",
        type="Campus (planned)",
        city="Nashik",
        state="Maharashtra",
        country="India",
        region="Global",
        status="planned",
    ),
    # —— Infrastructure (office printers & conference rooms) ——
    _fact(
        "infrastructure",
        "Office Printer",
        description="TOSHIBA e-STUDIO3505AC-11965425",
        detail_1="IPP http://10.1.0.22:50081/ipp/print",
        detail_2="Color · duplex · staple · chat 'print this' with PDF upload",
        resource_type="printer",
        model="Toshiba e-STUDIO3505AC",
        ipp_port=50081,
        printer_ip="10.1.0.22",
    ),
    _fact(
        "infrastructure",
        "Conference Room A",
        description="12-seat Teams Room with HDMI and video conferencing",
        detail_1="12 capacity · Teams Room",
        detail_2="Book via chat or Outlook calendar",
        resource_type="conference_room",
        capacity=12,
        av_equipment="Teams Room, HDMI",
    ),
    _fact(
        "infrastructure",
        "Conference Room B",
        description="6-seat conference room with display",
        detail_1="6 capacity",
        detail_2="HDMI display — bring your laptop",
        resource_type="conference_room",
        capacity=6,
        av_equipment="HDMI display",
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
    # —— Team (22) ——
    _team('Anjali "Ann" Ramakumaran', "Founder and Group CEO", "Ampcus"),
    _team("Salil Sankaran", "Group President", "Ampcus"),
    _team("Ramana Challa", "Chief Operating Officer", "Operations"),
    _team("Charles McMahon", "Executive Vice President", "Ampcus"),
    _team("Danielle Gardiner", "Chief Forensics Officer", "Ampcus Forensics"),
    _team("Chris Brosnan", "Chief Revenue Officer", "Ampcus Cyber — US"),
    _team("Joe Scarlato", "Executive Vice President", "Ampcus Forensics"),
    _team("Biju George", "Executive Vice President", "SLED and Utilities"),
    _team("Donna Howell", "Senior Vice President", "Customer Success"),
    _team("Samir Sankaran", "Senior Vice President", "Federal Operations and Delivery"),
    _team("Sanjeev Chauhan", "Senior Vice President", "Enterprise Solutions"),
    _team("Carlos Rivera", "Senior Vice President", "Ampcus Forensics — LATAM"),
    _team("Phani Kumar", "Senior Vice President", "Client Partner"),
    _team("Jim Jacobsen", "Senior Vice President", "Business Development"),
    _team("Karen Kok", "Senior Vice President", "Ampcus"),
    _team("Oma Taiga", "Vice President", "Quality Center of Excellence"),
    _team("Kamal Vadrevu", "Vice President", "Customer Success"),
    _team("Rashme Vohra", "Vice President", "Client Partner"),
    _team("Shweta Bhanot", "Vice President", "Client Partner"),
    _team("Julie Potter", "Vice President of Sales", "Sales"),
    _team("Abhishek Gautam", "Vice President", "Client Partner"),
    _team("Laurie Smith", "Senior Manager", "Human Resources"),
    # —— Partnerships (18 — Ampcus Partners page) ——
    _partner("SAP", "Enterprise software & platforms"),
    _partner("Oracle", "Enterprise software & platforms"),
    _partner("Salesforce", "Enterprise software & platforms"),
    _partner("Appian", "Enterprise software & platforms"),
    _partner("VMware", "Enterprise software & platforms"),
    _partner("UiPath", "Automation & AI"),
    _partner("Snowflake", "Automation & AI"),
    _partner("BlackBerry", "Cybersecurity & communications"),
    _partner("Avaya", "Cybersecurity & communications"),
    _partner("Cisco", "Cybersecurity & communications"),
    _partner("Ruckus", "Cybersecurity & communications"),
    _partner("SAS", "Analytics"),
    _partner("Terremark", "Cloud & infrastructure"),
    _partner("ns2", "Cloud & infrastructure"),
    _partner("Carpathia", "Cloud & infrastructure"),
    _partner(
        "Microsoft",
        "Technology alliance",
        description="Microsoft technology alliance partner",
        alliance_level="Gold Partner",
    ),
    _partner("Alliance for Science", "Community & advocacy"),
    _partner("Diversity Alliance", "Community & advocacy"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_details_column(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(company_facts)").fetchall()}
    if "details" not in cols:
        conn.execute("ALTER TABLE company_facts ADD COLUMN details TEXT")


def _seed_is_current(conn) -> bool:
    """True when DB matches the current seed revision and row count."""
    total = conn.execute("SELECT COUNT(*) AS n FROM company_facts").fetchone()["n"]
    if int(total or 0) < len(_SEED):
        return False
    marker = conn.execute(
        """
        SELECT details FROM company_facts
        WHERE category = 'services' AND name = 'AI, GenAI & Agentic AI'
        LIMIT 1
        """
    ).fetchone()
    if not marker:
        return False
    hq = conn.execute(
        """
        SELECT details FROM company_facts
        WHERE category = 'locations' AND name = 'Chantilly, VA'
        LIMIT 1
        """
    ).fetchone()
    if not hq:
        return False
    try:
        hq_details = json.loads(hq["details"] or "{}")
    except json.JSONDecodeError:
        return False
    if not hq_details.get("is_headquarters"):
        return False
    rev = conn.execute(
        """
        SELECT details FROM company_facts
        WHERE category = 'locations' AND name = 'U.S. Office Network'
        LIMIT 1
        """
    ).fetchone()
    if not rev:
        return False
    try:
        rev_details = json.loads(rev["details"] or "{}")
    except json.JSONDecodeError:
        return False
    return int(rev_details.get("seed_revision") or 0) == SEED_REVISION


def seed_company_facts_if_empty() -> int:
    """Upsert the official Ampcus company-facts seed."""
    init_audit_db()
    with _lock:
        with connect() as conn:
            _ensure_details_column(conn)
            if _seed_is_current(conn):
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
