"""Tests SQL builder — vérifie que les 4 statements sont bien formés."""

from __future__ import annotations

from pricetracker_indices.bq import IndicesConfig, build_sql_plan


def _config() -> IndicesConfig:
    return IndicesConfig(
        project_id="price-tracker-test",
        dataset_silver="prt_test_silver",
        dataset_gold="prt_test_gold",
        table_open_prices="open_prices_clean",
        table_aggregats="aggregats_enseignes",
        table_indices="indices_inflation",
        table_rankings="rankings_produits",
        table_anomalies="anomalies_detected",
        location="EU",
        min_observations=3,
        window_weeks_aggregats=12,
        window_weeks_rankings=8,
        z_threshold=3.0,
        top_n_rankings=500,
    )


def test_plan_returns_four_statements() -> None:
    plan = build_sql_plan(_config())
    assert [label for label, _ in plan] == [
        "aggregats_enseignes",
        "indices_inflation",
        "rankings_produits",
        "anomalies_detected",
    ]


def test_each_sql_references_correct_tables() -> None:
    plan = build_sql_plan(_config())
    by_label = dict(plan)

    src = "`price-tracker-test.prt_test_silver.open_prices_clean`"
    assert src in by_label["aggregats_enseignes"]
    assert src in by_label["indices_inflation"]
    assert src in by_label["rankings_produits"]
    assert src in by_label["anomalies_detected"]

    assert "`price-tracker-test.prt_test_gold.aggregats_enseignes`" in by_label["aggregats_enseignes"]
    assert "`price-tracker-test.prt_test_gold.indices_inflation`" in by_label["indices_inflation"]
    assert "`price-tracker-test.prt_test_gold.rankings_produits`" in by_label["rankings_produits"]
    assert "`price-tracker-test.prt_test_gold.anomalies_detected`" in by_label["anomalies_detected"]


def test_each_sql_starts_with_truncate_and_inserts() -> None:
    """Préserve les options Terraform : TRUNCATE + INSERT (pas CREATE OR REPLACE)."""
    plan = build_sql_plan(_config())
    for label, sql in plan:
        assert "TRUNCATE TABLE" in sql, f"{label} doit faire TRUNCATE"
        assert "INSERT INTO" in sql, f"{label} doit faire INSERT INTO"
        assert "CREATE OR REPLACE" not in sql, f"{label} ne doit PAS faire CREATE OR REPLACE"


def test_iqr_outliers_excluded_in_all_sql() -> None:
    """Les outliers IQR pré-flaggés par le cleaner ingestion sont exclus."""
    plan = build_sql_plan(_config())
    for label, sql in plan:
        assert "iqr_outlier" in sql, f"{label} doit filtrer iqr_outlier"
