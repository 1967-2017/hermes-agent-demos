.PHONY: demo demo1 demo2

demo: demo2

demo1:
	python -m demo1_ops.verify

demo2:
	python -m demo2_travel.verify

