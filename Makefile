.PHONY: demo demo1 demo2 verify-demo2 demo3 demo3-index demo4 verify-demo4 demo4-check-mcp

demo: demo4

demo1:
	python -m demo1_ops.verify

demo2:
	python -m demo2_travel.main --scenario 1 --interactive

verify-demo2:
	python -m demo2_travel.verify

demo3-index:
	python -m demo3_rag.ingest

demo3:
	python -m demo3_rag.verify

demo4:
	conda run -n hermes-demos python -m demo4_blackboard.main --scenario multimodal_rag_2024

verify-demo4:
	conda run -n hermes-demos python -m demo4_blackboard.verify --scenario all

demo4-check-mcp:
	conda run -n hermes-demos python -m demo4_blackboard.check_mcp

