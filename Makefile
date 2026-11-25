PY ?= python

.PHONY: test selfcheck edge-audit preflight
test:
	env -u PYTHONPATH $(PY) -m pytest tests -q -p no:cacheprovider

selfcheck:
	env -u PYTHONPATH $(PY) anantara/sodex_governor.py --selfcheck

edge-audit:        # READ-ONLY: tidak mengirim order
	env -u PYTHONPATH $(PY) scripts/sodex_fleet_edge_audit.py

preflight:         # READ-ONLY: gerbang kesiapan live; exit != 0 bila ada blocker
	env -u PYTHONPATH $(PY) scripts/sodex_live_preflight.py
