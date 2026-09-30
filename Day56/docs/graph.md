# Decision workflow (generated - run `python -m scripts.draw_graph`)

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	input(input)
	policy_gate(policy_gate)
	policy_block(policy_block)
	constraint_guard(constraint_guard)
	route_input(route_input)
	fallback(fallback)
	uncertainty_review(uncertainty_review)
	risk_tool(risk_tool)
	rules(rules)
	provider_tool(provider_tool)
	cost_tool(cost_tool)
	select(select)
	llm_explain(llm_explain)
	fast_explain(fast_explain)
	tool_error(tool_error)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> input;
	cost_tool -.-> select;
	cost_tool -.-> tool_error;
	fallback --> finalize;
	fast_explain --> finalize;
	finalize --> constraint_guard;
	input --> policy_gate;
	llm_explain -.-> finalize;
	llm_explain -.-> uncertainty_review;
	policy_block --> finalize;
	policy_gate -.-> policy_block;
	policy_gate -.-> route_input;
	provider_tool -.-> cost_tool;
	provider_tool -.-> tool_error;
	risk_tool -.-> rules;
	risk_tool -.-> tool_error;
	route_input -.-> fallback;
	route_input -.-> risk_tool;
	rules -.-> fast_explain;
	rules -.-> llm_explain;
	rules -.-> provider_tool;
	select -.-> fast_explain;
	select -.-> llm_explain;
	tool_error --> finalize;
	uncertainty_review --> finalize;
	constraint_guard --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```
