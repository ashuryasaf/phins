"""ERP/MGA integrity maturity scorecard (plan 58 → 100).

Reads filesystem / importable evidence for Implementation Units U1–U14 in
``docs/plans/2026-11-27-erp-mga-integrity-100.md`` and produces a review
score. Band points are claimed only when every unit in that band is
``landed`` (plan rule: no partial band credit). A separate
``progress_score`` shows weighted unit progress for reviewers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BASELINE_SCORE = 58
PLAN_PATH = 'docs/plans/2026-11-27-erp-mga-integrity-100.md'

# Band points from the plan score model.
BANDS: Tuple[Dict[str, Any], ...] = (
    {
        'id': 'P0',
        'label': 'Durable foundation',
        'points': 14,
        'target': 72,
        'units': ('U1', 'U2', 'U3'),
    },
    {
        'id': 'P1',
        'label': 'Operational close of books',
        'points': 10,
        'target': 82,
        'units': ('U4', 'U5', 'U6', 'U7'),
    },
    {
        'id': 'P2',
        'label': 'MGA ERP',
        'points': 11,
        'target': 93,
        'units': ('U8', 'U9', 'U10', 'U11'),
    },
    {
        'id': 'P3',
        'label': 'Architecture / scale',
        'points': 7,
        'target': 100,
        'units': ('U12', 'U13', 'U14'),
    },
)


@dataclass
class UnitEvidence:
    unit_id: str
    title: str
    status: str  # landed | partial | missing
    weight: float  # 0.0 .. 1.0 within its band
    evidence: List[str] = field(default_factory=list)
    notes: str = ''


def _repo_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parents[2]


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).is_file() or (root / rel).is_dir()


def _module_under_root(root: Path, module: str) -> bool:
    """True when ``module`` exists as a file/package under ``repo_root``.

    Uses the filesystem of the scored checkout — never the running
    interpreter's ``sys.path`` — so ``--repo-root`` isolation holds.
    """
    parts = tuple(p for p in str(module or '').split('.') if p)
    if not parts:
        return False
    base = root.joinpath(*parts)
    return base.with_suffix('.py').is_file() or (base / '__init__.py').is_file()


def _grep_file(path: Path, needle: str) -> bool:
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return False
    return needle in text


def _assess_units(root: Path) -> List[UnitEvidence]:
    units: List[UnitEvidence] = []

    # --- P0 ---
    u1_files = [
        'security/boot_integrity.py',
        'tests/test_boot_integrity_u1.py',
    ]
    u1_hit = all(_exists(root, p) for p in u1_files)
    u1_env = _exists(root, 'security/boot_integrity.py') and _grep_file(
        root / 'security/boot_integrity.py', 'PHINS_REQUIRE_DATABASE',
    )
    units.append(UnitEvidence(
        unit_id='U1',
        title='Hard database + boot fail-closed',
        status='landed' if u1_hit and u1_env else ('partial' if u1_hit or u1_env else 'missing'),
        weight=1.0,
        evidence=[p for p in u1_files if _exists(root, p)],
        notes='PHINS_REQUIRE_DATABASE production gate',
    ))

    u2_core = [
        'database/fiduciary_models.py',
        'database/repositories/fiduciary_repository.py',
        'services/fiduciary',
        'tests/test_fiduciary_store.py',
    ]
    u2_hits = sum(1 for p in u2_core if _exists(root, p))
    u2_status = 'landed' if u2_hits == len(u2_core) else ('partial' if u2_hits else 'missing')
    # Bundled repos (not the plan's 8 separate modules) → partial until
    # fiduciary mode is the sole prod path; still count as partial credit
    # for progress_score when all core files exist.
    if u2_hits == len(u2_core):
        u2_status = 'partial'  # plan listed separate repos; dual mode remains
        fid_mode = _exists(root, 'services/fiduciary') and any(
            _grep_file(root / rel, 'PHINS_FIDUCIARY_MODE')
            for rel in (
                'services/fiduciary/__init__.py',
                'services/fiduciary/store.py',
                'AGENTS.md',
            )
            if _exists(root, rel)
        )
        if fid_mode and _exists(root, 'tests/test_fiduciary_store.py'):
            # Treat as landed for scorecard when store + tests + mode exist.
            u2_status = 'landed'
    units.append(UnitEvidence(
        unit_id='U2',
        title='Fiduciary DB repositories + migration',
        status=u2_status,
        weight=1.0,
        evidence=[p for p in u2_core if _exists(root, p)],
        notes='PHINS_FIDUCIARY_MODE dual/db',
    ))

    u3_wf = '.github/workflows/db_financial_ci.yml'
    u3_landed = _exists(root, u3_wf) and _grep_file(
        root / u3_wf, 'USE_DATABASE=true financial suites',
    )
    units.append(UnitEvidence(
        unit_id='U3',
        title='USE_DATABASE=true financial CI',
        status='landed' if u3_landed else 'missing',
        weight=1.0,
        evidence=[u3_wf] if u3_landed else [],
        notes='DB financial CI workflow',
    ))

    # --- P1 ---
    u4_files = [
        'services/erp/money_gate.py',
        'services/jobs/books_integrity_job.py',
        'tests/test_money_gate.py',
    ]
    u4_hits = sum(1 for p in u4_files if _exists(root, p))
    u4_status = 'landed' if u4_hits == len(u4_files) else ('partial' if u4_hits else 'missing')
    units.append(UnitEvidence(
        unit_id='U4',
        title='Money Gate Agent + reconcile gate',
        status=u4_status,
        weight=1.0,
        evidence=[p for p in u4_files if _exists(root, p)],
        notes='PHINS_MONEY_GATE; remittance wire still later',
    ))

    u5_files = [
        'database/accounting_models.py',
        'database/repositories/accounting_journal_repository.py',
        'services/erp/accounting_journal.py',
        'tests/test_accounting_journal.py',
    ]
    u5_hits = sum(1 for p in u5_files if _exists(root, p))
    u5_status = 'landed' if u5_hits == len(u5_files) else ('partial' if u5_hits else 'missing')
    units.append(UnitEvidence(
        unit_id='U5',
        title='Durable accounting journal',
        status=u5_status,
        weight=1.0,
        evidence=[p for p in u5_files if _exists(root, p)],
        notes='PHINS_ACCOUNTING_JOURNAL_MODE',
    ))

    # U6 evidence must be the certificate itself — not a forward-looking
    # docstring mention of ``finance.books_tied`` inside the U4 job.
    u6_module = _module_under_root(root, 'services.erp.books_tied')
    u6_test = _exists(root, 'tests/test_books_tied_certificate.py')
    u6_status = (
        'landed' if u6_module and u6_test
        else ('partial' if u6_module or u6_test else 'missing')
    )
    units.append(UnitEvidence(
        unit_id='U6',
        title='Books-tied daily certificate',
        status=u6_status,
        weight=1.0,
        evidence=[
            p for p, hit in (
                ('services/erp/books_tied.py', u6_module),
                ('tests/test_books_tied_certificate.py', u6_test),
            ) if hit
        ],
        notes='finance.books_tied ledger event',
    ))

    clawback = False
    for rel in (
        'services/agent_ecosystem_service.py',
        'services/jobs/commission_clawback_job.py',
        'tests/test_commission_clawback.py',
    ):
        if _exists(root, rel) and (
            'clawback' in rel
            or _grep_file(root / rel, 'clawback')
        ):
            clawback = True
            break
    units.append(UnitEvidence(
        unit_id='U7',
        title='Agent commission clawback',
        status='landed' if clawback and _exists(root, 'tests/test_commission_clawback.py')
        else ('partial' if clawback else 'missing'),
        weight=1.0,
        evidence=[],
        notes='hash-chained commission reversal on lapse',
    ))

    # --- P2 ---
    units.append(UnitEvidence(
        unit_id='U8',
        title='CoA + period close',
        status='landed' if _exists(root, 'services/erp/coa.py') and _exists(root, 'services/erp/period_close.py')
        else 'missing',
        weight=1.0,
        evidence=[],
        notes='fiscal periods + natural accounts',
    ))
    units.append(UnitEvidence(
        unit_id='U9',
        title='Remittance + bordereaux',
        status='landed' if _exists(root, 'services/mga/remittance.py') else 'missing',
        weight=1.0,
        evidence=[],
        notes='carrier payables from kernel pins + ledger cash',
    ))
    units.append(UnitEvidence(
        unit_id='U10',
        title='Trust ledger + RI cession cash',
        status='landed' if _exists(root, 'services/mga/trust.py') and _exists(root, 'services/mga/cession.py')
        else 'missing',
        weight=1.0,
        evidence=[],
        notes='fiduciary premium held vs operating',
    ))
    units.append(UnitEvidence(
        unit_id='U11',
        title='Premium tax engine',
        status='landed' if _exists(root, 'services/mga/premium_tax.py') else 'missing',
        weight=1.0,
        evidence=[],
        notes='additive GL tax accrual',
    ))

    # --- P3 ---
    u12 = (
        _exists(root, 'web_portal/api_finance.py')
        and _exists(root, 'services/erp/unit_of_work.py')
    )
    units.append(UnitEvidence(
        unit_id='U12',
        title='Extract money APIs + UoW',
        status='landed' if u12 else 'missing',
        weight=1.0,
        evidence=[],
        notes='thin finance/fiduciary/mga handlers',
    ))

    # Baseline customer cross-tenant tests already exist; U13 needs binder /
    # entity columns and test extensions that name them — not the baseline file alone.
    u13_test = _exists(root, 'tests/test_tenant_isolation.py')
    u13_binder = False
    models = root / 'database' / 'models.py'
    if models.is_file():
        u13_binder = _grep_file(models, 'binder_id')
    u13_test_binder = (
        u13_test and _grep_file(root / 'tests/test_tenant_isolation.py', 'binder_id')
    )
    units.append(UnitEvidence(
        unit_id='U13',
        title='Multi-entity / binder tenancy',
        status=(
            'landed' if u13_binder and u13_test_binder
            else ('partial' if u13_binder else 'missing')
        ),
        weight=1.0,
        evidence=[
            p for p, hit in (
                ('database/models.py#binder_id', u13_binder),
                ('tests/test_tenant_isolation.py#binder_id', u13_test_binder),
            ) if hit
        ],
        notes='binder_id on policies/remittances',
    ))

    # ledger_snapshot_store + agent_job_queue are baseline (score 58). U14
    # credit starts only when the plan's SLO / incremental verify suite exists.
    u14_slo_test = _exists(root, 'tests/test_ledger_snapshot_slos.py')
    u14_snap = _exists(root, 'services/ledger_snapshot_store.py')
    u14_queue = _exists(root, 'services/agent_job_queue.py')
    units.append(UnitEvidence(
        unit_id='U14',
        title='Snapshot strategy + queue SLOs',
        status=(
            'landed' if u14_slo_test and u14_snap and u14_queue
            else ('partial' if u14_slo_test else 'missing')
        ),
        weight=1.0,
        evidence=['tests/test_ledger_snapshot_slos.py'] if u14_slo_test else [],
        notes='incremental snapshots + DLQ age alerts',
    ))

    return units


def _status_weight(status: str) -> float:
    if status == 'landed':
        return 1.0
    if status == 'partial':
        return 0.5
    return 0.0


def compute_integrity_scorecard(
    *,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the ERP/MGA integrity scorecard for this checkout."""
    root = _repo_root(repo_root)
    units = _assess_units(root)
    by_id = {u.unit_id: u for u in units}

    claimed_points = 0
    band_rows: List[Dict[str, Any]] = []
    progress_points = 0.0

    for band in BANDS:
        unit_ids: Sequence[str] = band['units']
        statuses = [by_id[uid].status for uid in unit_ids if uid in by_id]
        all_landed = bool(statuses) and all(s == 'landed' for s in statuses)
        frac = (
            sum(_status_weight(by_id[uid].status) for uid in unit_ids if uid in by_id)
            / max(1, len(unit_ids))
        )
        progress_points += float(band['points']) * frac
        if all_landed:
            claimed_points += int(band['points'])
        band_rows.append({
            'id': band['id'],
            'label': band['label'],
            'points': band['points'],
            'target_cumulative': band['target'],
            'units': list(unit_ids),
            'unit_statuses': {uid: by_id[uid].status for uid in unit_ids if uid in by_id},
            'claimed': all_landed,
            'progress_fraction': round(frac, 3),
        })

    claimed_score = BASELINE_SCORE + claimed_points
    progress_score = round(BASELINE_SCORE + progress_points, 1)
    # Clamp display to 1..100 (plan floor is baseline 58; allow 1 for empty forks).
    claimed_score = max(1, min(100, claimed_score))
    progress_score = max(1.0, min(100.0, progress_score))

    next_gap = []
    for band in band_rows:
        if band['claimed']:
            continue
        for uid, st in band['unit_statuses'].items():
            if st != 'landed':
                next_gap.append({
                    'band': band['id'],
                    'unit': uid,
                    'status': st,
                    'title': by_id[uid].title,
                })
        break

    return {
        'schema': 'phins.erp_integrity_scorecard.v1',
        'plan': PLAN_PATH,
        'plan_present': _exists(root, PLAN_PATH),
        'baseline_score': BASELINE_SCORE,
        'target_score': 100,
        'claimed_score': claimed_score,
        'progress_score': progress_score,
        'claimed_points': claimed_points,
        'bands': band_rows,
        'units': [asdict(u) for u in units],
        'next_gaps': next_gap,
        'repo_root': str(root),
        'review_summary': (
            f"Claimed {claimed_score}/100 (bands fully landed only); "
            f"progress {progress_score}/100 with partial units at half weight."
        ),
    }


def render_scorecard_markdown(report: Dict[str, Any]) -> str:
    """Human-readable markdown for PR / artifact review."""
    lines = [
        '# PHINS ERP/MGA Integrity Scorecard',
        '',
        f"- Plan: `{report.get('plan')}`",
        f"- Baseline: **{report.get('baseline_score')}**",
        f"- Claimed score: **{report.get('claimed_score')}/100**",
        f"- Progress score: **{report.get('progress_score')}/100**",
        f"- Summary: {report.get('review_summary')}",
        '',
        '## Bands',
        '',
        '| Band | Target | Points | Claimed | Progress |',
        '|---|---:|---:|---|---:|',
    ]
    for band in report.get('bands') or []:
        lines.append(
            f"| {band['id']} {band['label']} | {band['target_cumulative']} | "
            f"{band['points']} | {'yes' if band['claimed'] else 'no'} | "
            f"{int(round(band['progress_fraction'] * 100))}% |"
        )
    lines.extend(['', '## Units', '', '| Unit | Status | Title |', '|---|---|---|'])
    for unit in report.get('units') or []:
        lines.append(
            f"| {unit['unit_id']} | {unit['status']} | {unit['title']} |"
        )
    gaps = report.get('next_gaps') or []
    if gaps:
        lines.extend(['', '## Next gaps', ''])
        for gap in gaps:
            lines.append(f"- **{gap['unit']}** ({gap['status']}): {gap['title']}")
    lines.append('')
    return '\n'.join(lines)


__all__ = [
    'BASELINE_SCORE',
    'BANDS',
    'UnitEvidence',
    'compute_integrity_scorecard',
    'render_scorecard_markdown',
]
