# Demo 4 Validation Report

Run validation with:

```powershell
conda run -n hermes-demos python -m demo4_blackboard.verify --scenario all
```

Expected checks:

- [ ] 方案覆盖: final review contains grounded synthesis and references.
- [ ] 真实检索: Researcher uses `search_arxiv` and references come from tool results.
- [ ] 虚假引用检测: Critic reviews citation support and sets `approve=false` for unsupported notes.
- [ ] 冷门主题优雅降级: sparse evidence produces `资料不足` or a non-consensus final review.

