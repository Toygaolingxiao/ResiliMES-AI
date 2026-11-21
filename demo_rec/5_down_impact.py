"""Shot: DOWN tools, blocked lots, materials those lots need — grouped by material. Prints no secrets."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from resilimes.config import load_settings  # noqa: E402  (loads .env)
load_settings()
from agent.tools_zetaris import rows_as_dicts, run_sql  # noqa: E402

SQL = """SELECT mat.material_id, mat.name, COUNT(DISTINCT e.equipment_id) AS down_tools, COUNT(DISTINCT w.job_id) AS blocked_lots
FROM resilimes.equipment e
JOIN fab_cmms.maintenance_logs m ON e.equipment_id = m.equipment_id
JOIN resilimes.wip_jobs w ON e.equipment_id = w.assigned_equipment
JOIN fab_erp.bom b ON w.product_id = b.product_id
JOIN fab_erp.materials mat ON b.material_id = mat.material_id
WHERE e.status = 'DOWN'
GROUP BY mat.material_id, mat.name
ORDER BY blocked_lots DESC"""

print("Zetaris federated query: MES (resilimes) + maintenance (fab_cmms) + ERP (fab_erp)\n")
print(SQL + "\n")
t0 = time.perf_counter()
payload = run_sql(SQL, timeout_s=60)
wall = time.perf_counter() - t0
rows = rows_as_dicts(payload)
cols = ["material_id", "name", "down_tools", "blocked_lots"]
w = {c: max([len(c)] + [len(str(r.get(c, ""))) for r in rows]) for c in cols}
print("  ".join(c.ljust(w[c]) for c in cols))
print("  ".join("-" * w[c] for c in cols))
for r in rows:
    print("  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))
used = payload.get("timeUsed") if isinstance(payload, dict) else None
print(f"\n{len(rows)} materials from 3 systems in {wall:.1f} s" + (f"  (Zetaris timeUsed: {used})" if used is not None else ""))
