#!/usr/bin/env bash
# End-to-end verification: login -> plan generation -> grounded Q&A ->
# off-topic refusal -> VLM inspection. Requires backend on :8000 (see run.py)
# and the demo image at data/demo_part.jpg. Run from the project root:
#   bash scripts/e2e_verify.sh
set -uo pipefail
BASE=${BASE:-http://localhost:8000}
IMG=${IMG:-data/demo_part.jpg}
TMP=${E2E_TMP:-_e2e_tmp}
mkdir -p "$TMP"

TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"copilot-demo-123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "${TOKEN:-}" ]; then echo "FAIL: could not log in"; exit 1; fi
echo "1/5 login OK (token acquired)"

echo "2/5 plan generation:"
curl -s -o "$TMP/plan.json" -w "  HTTP %{http_code}\n" -X POST "$BASE/api/v1/plans/generate" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"requirements":{"part_number":"SHF-350-A","material":"AISI 1045","quantity":250,"tolerance_grade":"IT7","surface_finish_um":1.6}}'
python - "$TMP/plan.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
if "error" in d: print("  ERROR:", d["error"].get("message", "")[:200])
else:
    plan = d.get("plan", {})
    print("  plan:", (plan.get("plan_title") or d.get("title", "?"))[:70])
    print("  ops:", len(plan.get("operations", [])),
          "| validation ok:", (d.get("validation") or {}).get("ok"),
          "| grounded ops:", (d.get("grounding") or {}).get("operations_with_citations"))
PY

echo "3/5 grounded Q&A:"
curl -s -o "$TMP/qa.json" -w "  HTTP %{http_code}\n" -X POST "$BASE/api/v1/qa/ask" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"What surface finish and coolant do we specify for shaft turning?"}'
python - "$TMP/qa.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("  refused:", d.get("refused"), "| citations:", len(d.get("citations", [])),
      "| conf:", d.get("confidence"))
print("  answer:", d.get("answer", "")[:140])
PY

echo "4/5 off-topic -> general chat:"
curl -s -o "$TMP/qa2.json" -w "  HTTP %{http_code}\n" -X POST "$BASE/api/v1/qa/ask" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"How long do I barbecue a beef brisket?"}'
python - "$TMP/qa2.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("  mode:", d.get("mode"), "| refused:", d.get("refused"),
      "| reason:", d.get("refusal_reason", ""), "| conf:", d.get("confidence"))
print("  answer:", d.get("answer", "")[:140])
PY

echo "5/5 VLM inspection:"
curl -s -o "$TMP/insp.json" -w "  HTTP %{http_code}\n" \
  -X POST "$BASE/api/v1/inspections/analyze?part_number=SHF-350-A" \
  -H "Authorization: Bearer $TOKEN" -F "file=@$IMG"
python - "$TMP/insp.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
res = d.get("result", {})
q = d.get("quality", {})
print("  image gate:", "PASS" if q.get("passed") else "FAIL",
      "| status:", d.get("status", "?"),
      "| verdict:", res.get("verdict", "?"),
      "| conf:", res.get("confidence"))
print("  explanation:", (res.get("explanation") or res.get("error") or "")[:140])
PY

rm -rf "$TMP"
echo "done"
