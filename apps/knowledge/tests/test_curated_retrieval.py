"""Synthetic evidence cases for curated oxygen scope and ranking."""

from datetime import datetime, timezone
import unittest

from apps.knowledge.curated_retrieval import (
    is_curated_quantitative_question, is_standalone_oxygen_lookup, search_curated_oxygen,
)


_AT = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)


def _interval(low, high, *, low_inclusive=True, high_inclusive=True):
    return {
        "low": low, "high": high,
        "low_inclusive": low_inclusive, "high_inclusive": high_inclusive,
    }


def _card(identifier, intervals=(), *, outcomes=("feeding",), keywords=("溶氧",)):
    return {
        "id": identifier, "title": f"合成研究 {identifier}", "body": f"日本鳗鲡的合成研究 {identifier}。",
        "source_url": f"https://example.invalid/{identifier}", "source_version": "fixture",
        "species": "anguilla_japonica", "keywords": keywords, "outcomes": outcomes,
        "oxygen_intervals": intervals,
    }


class CuratedOxygenRetrievalTests(unittest.TestCase):
    def search(self, query, cards, *, intent_text=None, top_k=3):
        return search_curated_oxygen(
            query, cards, top_k=top_k, retrieved_at=_AT, intent_text=intent_text,
        )

    def test_general_aliases_retrieve_cited_eel_studies_and_preserve_scope(self):
        card = _card("feeding")
        for query in ("低氧时鳗鱼还吃食吗", "查日本鳗鲡溶存氧和摄食的资料", "DO 鳗鱼食欲",
                      "dissolved_oxygen"):
            with self.subTest(query=query):
                (evidence,) = self.search(query, [card])
                self.assertEqual(evidence.text, card["body"])
                self.assertEqual(evidence.source_id, card["source_url"])
                self.assertEqual(evidence.source_version, card["source_version"])
                self.assertEqual(evidence.source_title, card["title"])
                self.assertEqual(evidence.retrieved_at, _AT)

    def test_unrelated_query_is_distinct_from_no_matching_oxygen_evidence(self):
        self.assertIsNone(self.search("水温对鳗鲡的作用", []))
        self.assertIsNone(self.search("鳗鲡养殖记录", []))
        self.assertIsNone(self.search("How do eels reproduce?", []))
        self.assertEqual(self.search("查鳗鲡摄食的溶解氧资料", []), ())

    def test_uses_outcome_and_ranks_direct_support_before_partial(self):
        direct = _card("range", [_interval("1", "3")])
        point = _card("point", [_interval("2.95", "2.95")], keywords=("溶氧", "2.95", "日本鳗鲡"))
        other_outcome = _card("growth-only", [_interval("1", "3")], outcomes=("growth",))
        result = self.search("日本鳗鲡溶氧 1 至 3 mg/L 时还吃食吗", [point, other_outcome, direct], top_k=2)
        self.assertEqual([item.evidence_id for item in result], ["range", "point"])
        self.assertEqual(result[0].text, direct["body"])
        self.assertIn("实验点 2.95 mg/L", result[1].text)
        self.assertIn("不能据此推断整个区间", result[1].text)
        self.assertTrue(result[1].text.endswith(point["body"]))

    def test_exact_research_point_and_uncovered_numbers(self):
        card = _card("point", [_interval("2.95", "2.95")])
        result = self.search("日本鳗鱼溶氧 ２．９５ｍｇ／Ｌ 摄食", [card])
        self.assertEqual([item.text for item in result], [card["body"]])
        self.assertEqual(self.search("鳗鱼溶氧 3.1 mg/L 摄食", [card, _card("general")]), ())

    def test_boundary_inclusiveness_is_not_inferred(self):
        boundary = _card("boundary", [_interval("3", "3")])
        cases = (("低于 3 mg/L", False), ("<3 mg/L", False), ("≤ 3 mg/L", True),
                 ("不超过 3 mg/L", True), ("不高于 3 mg/L", True), ("不低于 3 mg/L", True),
                 ("1–3 mg/L", True), ("1–2.999 mg/L", False))
        for condition, matches in cases:
            with self.subTest(condition=condition):
                self.assertEqual(
                    bool(self.search(f"鳗鲡溶氧 {condition} 摄食", [boundary])), matches,
                )
        open_range = _card("open-range", [_interval("1", "3", high_inclusive=False)])
        self.assertFalse(self.search("鳗鲡溶氧 3 mg/L 摄食", [open_range]))
        result = self.search("鳗鲡溶氧 2–4 mg/L 摄食", [open_range])
        self.assertIn("[2, 3) mg/L", result[0].text)

    def test_multiple_or_unsupported_units_do_not_broaden_to_a_general_study(self):
        cards = [_card("general"), _card("point", [_interval("3", "3")])]
        for condition in (
            "1–3 ppm", "20%饱和度", "3 mg/dL", "3 mg/L/min", "3 mg/L·h",
            "3 mg/L · h", "3 毫克每升每小时", "约 3 mg/L",
            "-3 mg/L", "–3 mg/L", "3–1 mg/L", "1、3 mg/L", "1 mg/L 和 3 mg/L",
            "3 mg/L、水温 27°C", "1–3 mg/L 与 3–5 mg/L",
        ):
            with self.subTest(condition=condition):
                self.assertEqual(self.search(f"鳗鲡溶氧 {condition} 摄食", cards), ())

    def test_question_values_override_rewritten_terms_and_resolve_short_followup(self):
        cards = [_card("low", [_interval("1.1", "1.1")]), _card("higher", [_interval("3.6", "3.6")])]
        for query in ("溶氧鳗鲡摄食", "溶氧 1–2 mg/L 鳗鲡摄食"):
            with self.subTest(query=query):
                result = self.search(query, cards, intent_text="那 2–4 mg/L 呢？")
                self.assertEqual([item.evidence_id for item in result], ["higher"])
                self.assertIn("实验点 3.6 mg/L", result[0].text)
        self.assertEqual(self.search("溶氧 3.6 mg/L", cards, intent_text="溶氧 3.6 ppm 呢？"), ())

    def test_other_species_other_metric_and_current_only_are_excluded(self):
        card = _card("feeding")
        for question in (
            "欧洲鳗鲡溶氧和摄食", "Anguilla anguilla 溶氧与摄食", "A. anguilla 溶氧",
            "罗非鱼溶氧与食欲", "溶氧不是 3 mg/L 时的摄食", "我不问鳗鲡溶氧",
            "pH 和溶氧的共同影响", "水温会影响日本鳗鲡摄食吗", "本池现在溶氧低是不是让鱼不吃食",
            "How does dissolved oxygen affect feeding in salmon?",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.search("鳗鲡溶氧摄食研究", [card], intent_text=question), ())
        result = self.search(
            "鳗鲡溶氧摄食研究", [card],
            intent_text="日本鳗鲡的溶氧摄食试验怎么说，跟本池现在的情况一样吗？",
        )
        self.assertEqual([item.evidence_id for item in result], ["feeding"])

    def test_original_topic_and_species_cannot_be_invented_by_tool_query(self):
        card = _card("feeding", [_interval("2.11", "2.11")])
        tool_query = "日本鳗鲡 溶解氧 2.11 mg/L 摄食率"
        for question in (
            "锦鲤蛋白质换料比例如何？",
            "查马来鳗鲡溶解氧 2.11 mg/L 摄食率",
            "查俄罗斯鲟溶解氧 2.11 mg/L 摄食率",
            "日本鳗鲡与俄罗斯鲟在溶解氧 2.11 mg/L 时摄食如何？",
            "俄罗斯鲟和日本鳗鲡在溶解氧 2.11 mg/L 时摄食如何？",
            "项目资料怎么说，跟本池现在的情况一样吗？",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.search(tool_query, [card], intent_text=question), ())

    def test_original_scope_and_outcome_filter_wrong_rewrites(self):
        feeding = _card("feeding", [_interval("2.11", "2.11")])
        growth = _card("growth", [_interval("2.11", "2.11")], outcomes=("growth",))
        feeding_question = "请查日本鳗鲡溶解氧 2.11 mg/L 摄食率"
        result = self.search("欧洲鳗鲡 pH 2.11 mg/L 增重", [feeding, growth], intent_text=feeding_question)
        self.assertEqual([item.evidence_id for item in result], ["feeding"])
        self.assertEqual(self.search(
            feeding_question, [feeding], intent_text="日本鳗鲡溶解氧 2.11 mg/L 时的死亡率？",
        ), ())
        self.assertEqual(self.search(
            feeding_question, [feeding], intent_text="日本鳗鲡溶解氧 2.11 mg/L 时的脂肪含量？",
        ), ())
        self.assertEqual(self.search(
            feeding_question, [feeding], intent_text="日本鳗鲡溶解氧 2.11 mg/L 时会停食吗？",
        )[0].evidence_id, "feeding")

    def test_explicit_saturation_matches_own_unit_even_at_same_numeric_value(self):
        concentration = _card("concentration", [_interval("21.1", "21.1")])
        saturation = dict(_card("saturation"), oxygen_saturation_intervals=[_interval("21.1", "21.1")])
        cards = [concentration, saturation]
        for question in (
            "日本鳗鲡溶氧饱和度 21.1% 时的摄食率？",
            "日本鳗鲡溶氧 21.1% 饱和度下的摄食率？",
            "日本鳗鲡在 ２１．１％氧饱和度时的摄食率？",
        ):
            with self.subTest(question=question):
                result = self.search("日本鳗鲡溶氧 21.1 mg/L 摄食率", cards, intent_text=question)
                self.assertEqual([item.evidence_id for item in result], ["saturation"])
        result = self.search("日本鳗鲡溶氧 21.1 mg/L 摄食率", cards)
        self.assertEqual([item.evidence_id for item in result], ["concentration"])
        result = self.search("日本鳗鲡溶氧饱和度 20–30% 时的摄食率？", cards)
        self.assertEqual([item.evidence_id for item in result], ["saturation"])
        self.assertIn("21.1 % 饱和度", result[0].text)
        self.assertIn("不能据此推断整个区间", result[0].text)
        self.assertEqual(self.search("日本鳗鲡溶氧 21.1% 时的摄食率？", cards), ())
        self.assertEqual(self.search("日本鳗鲡摄食率 21.1% 时氧饱和度是多少？", cards), ())
        self.assertEqual(self.search("日本鳗鲡溶氧饱和度 21.1% 时的摄食率？", [concentration]), ())

    def test_bounded_reply_requires_one_explicit_scope_and_no_field_or_other_task(self):
        for question in (
            "日本鳗鲡溶氧 2.11 mg/L 的摄食率是多少？",
            "日本鳗鲡溶氧 1–3 mg/L 时会停食吗？",
            "查日本鳗鲡溶氧 9–10 mg/L 的摄食率文献",
            "日本鳗鲡溶氧在 ２１．１％饱和度时摄食如何？",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_curated_quantitative_question(question))
        for question in (
            "那 2–4 mg/L 呢？",
            "日本鳗鲡溶氧 2.11 mg/L 时摄食与增重各是多少？",
            "日本鳗鲡溶氧 2.11 mg/L 的死亡率是多少？",
            "日本鳗鲡溶氧 2.11 mg/L 时应不应该投喂？",
            "日本鳗鲡溶氧 2.11 mg/L 的摄食率？同时查本池溶氧",
            "日本鳗鲡溶氧 2.11 mg/L 的摄食率和实验样本量是多少？",
            "日本鳗鲡溶氧 2.11 mg/L 的摄食率？另外解释什么是pH",
            "俄罗斯鲟溶氧 2.11 mg/L 的摄食率？",
            "日本鳗鲡溶氧 2.11 mg/L·h 的摄食率？",
            "日本鳗鲡溶氧 2.11 mg/L 与 4 mg/L 的摄食率？",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_curated_quantitative_question(question))

    def test_standalone_lookup_can_give_negative_result_for_unsupported_scope(self):
        for question in (
            "请查俄罗斯鲟在溶解氧 2.11 mg/L 的摄食率。",
            "日本鳗鲡在溶解氧 2.11 mg/L·h 时摄食如何？",
            "日本鳗鲡在 2.11 ppm 的溶解氧下摄食如何？",
            "日本鳗鲡溶氧 2.11 mg/L 的死亡率是多少？",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_standalone_oxygen_lookup(question))
                self.assertFalse(is_curated_quantitative_question(question))
        for question in (
            "锦鲤蛋白质换料比例如何？",
            "请查日本鳗鲡的溶氧资料，再查本池当前水温",
            "溶氧试验；报告一下设备状态",
            "日本鳗鲡溶氧 3 mg/L 时要不要投喂？",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_standalone_oxygen_lookup(question))
