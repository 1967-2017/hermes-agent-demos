.PHONY: demo demo1 demo2 demo3 demo3-index

demo: demo3

demo1:
	python -m demo1_ops.verify

demo2:
	python -m demo2_travel.verify

demo3-index:
	python -m demo3_rag.ingest

demo3:
	python -m demo3_rag.verify

