from app.db import init_db
from app.mikan import apply_hidden
from app.runtime_config import clear_week_hidden, list_hidden, replace_week_hidden


def test_week_filters_are_persistent_and_independent():
    init_db()
    replace_week_hidden(2026, "summer", 1, [{"bangumi_id": 101, "title": "番剧 A"}])
    replace_week_hidden(2026, "summer", 2, [{"bangumi_id": 202, "title": "番剧 B"}])

    monday = list_hidden(2026, "summer", 1)
    tuesday = list_hidden(2026, "summer", 2)
    assert [row["bangumi_id"] for row in monday] == [101]
    assert [row["bangumi_id"] for row in tuesday] == [202]

    # Replacing Monday must not remove Tuesday.
    replace_week_hidden(2026, "summer", 1, [{"bangumi_id": 303, "title": "番剧 C"}])
    assert [row["bangumi_id"] for row in list_hidden(2026, "summer", 1)] == [303]
    assert [row["bangumi_id"] for row in list_hidden(2026, "summer", 2)] == [202]

    clear_week_hidden(2026, "summer", 1)
    assert list_hidden(2026, "summer", 1) == []
    assert [row["bangumi_id"] for row in list_hidden(2026, "summer", 2)] == [202]


def test_apply_hidden_supports_normal_and_edit_modes():
    init_db()
    replace_week_hidden(2027, "winter", 3, [{"bangumi_id": 88, "title": "隐藏番剧"}])
    items = [
        {"bangumi_id": 77, "weekday": 3, "title": "显示番剧"},
        {"bangumi_id": 88, "weekday": 3, "title": "隐藏番剧"},
    ]
    normal, hidden_count = apply_hidden(items, 2027, "winter", include_hidden=False)
    assert hidden_count == 1
    assert [row["bangumi_id"] for row in normal] == [77]

    editing, hidden_count = apply_hidden(items, 2027, "winter", include_hidden=True)
    assert hidden_count == 1
    assert len(editing) == 2
    assert next(row for row in editing if row["bangumi_id"] == 88)["hidden"] is True


def test_all_weekday_sections_remain_editable_when_all_items_hidden():
    from app.mikan import group_by_weekday
    groups = group_by_weekday([{"bangumi_id": 1, "weekday": 5, "title": "X", "hidden": True}], include_hidden=False)
    assert len(groups) == 7
    friday = next(group for group in groups if group["weekday"] == 5)
    assert friday["items"] == []
    assert friday["hidden_count"] == 1
    assert friday["total_count"] == 1
