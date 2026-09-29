"""Streamlit dashboard for evaluation metrics."""

from __future__ import annotations

from pathlib import Path

import plotly.express as px
import streamlit as st

from sdlc_agents.metrics import queries


def main() -> None:
	st.set_page_config(page_title="SDLC Agent Evaluation", layout="wide")
	st.title("SDLC Agent Evaluation")
	db_path = Path(st.sidebar.text_input("Database path", "metrics.db"))
	if not db_path.exists():
		st.info("No evaluation data is available yet. Run an evaluation batch first.")
		return

	filters: dict[str, str | None] = {}
	st.sidebar.header("Filters")
	for column, label in (
		("batch_id", "Batch"),
		("model", "Model"),
		("prompt_version", "Prompt version"),
		("mode", "Mode"),
	):
		options = ["All"] + queries.filter_values(db_path, column)
		selected = st.sidebar.selectbox(label, options)
		filters[column] = None if selected == "All" else selected

	latency = queries.latency_by_agent(db_path, filters)
	cost = queries.cost_by_ticket(db_path, filters)
	accuracy = queries.accuracy_metrics(db_path, filters)
	pass_rates = queries.ticket_pass_rates(db_path, filters)

	st.subheader("Latency by agent")
	if latency.empty or latency["latency_ms"].dropna().eq(0).all():
		st.info("Latency is not recorded for the selected runs.")
	else:
		st.plotly_chart(px.box(latency, x="agent", y="latency_ms", points="all"), use_container_width=True)

	st.subheader("Cost per ticket")
	if cost.empty or cost["cost"].dropna().eq(0).all():
		st.info("Cost is not available for the selected runs. They contain no billable token usage.")
	else:
		st.plotly_chart(px.bar(cost, x="ticket_id", y="cost", color="agent", barmode="stack"), use_container_width=True)

	st.subheader("Accuracy")
	if accuracy.empty:
		st.info("No agent accuracy data matches the selected filters.")
	else:
		columns = st.columns(3)
		columns[0].metric("Mean correctness", f"{accuracy['correctness'].mean():.1%}")
		columns[1].metric("Uncertainty surfacing", f"{accuracy['uncertainty_surfacing'].mean(skipna=True):.1%}")
		columns[2].metric("False positive rate", f"{accuracy['false_positive'].mean():.1%}")
		st.dataframe(accuracy, use_container_width=True, hide_index=True)

	st.subheader("Pass rate by ticket")
	st.dataframe(pass_rates, use_container_width=True, hide_index=True)

	st.subheader("Success criteria")
	st.dataframe(queries.success_criteria(db_path), use_container_width=True, hide_index=True)


if __name__ == "__main__":
	main()
