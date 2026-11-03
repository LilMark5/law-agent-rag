"""法规正文解析测试

解析器的两个易错点：
1. 法规 docx 开头带目录，目录里的章标题与正文重复，直接顺序扫描会把目录当正文
2. 中文条号有「之一」（刑法修正案新增条款），不能只按数字递增判断
"""

from src.data.law_parser import ARTICLE_RE, cn_to_int, parse_law


class TestCnToInt:
    def test_simple(self):
        assert cn_to_int("九") == 9
        assert cn_to_int("十") == 10
        assert cn_to_int("十一") == 11
        assert cn_to_int("二十") == 20

    def test_compound(self):
        assert cn_to_int("一百二十") == 120
        assert cn_to_int("四百五十二") == 452
        assert cn_to_int("一千二百六十") == 1260

    def test_zero_variants(self):
        assert cn_to_int("一百零九") == 109
        assert cn_to_int("一百〇九") == 109


class TestArticleRegex:
    def test_plain_article(self):
        match = ARTICLE_RE.match("第一条　为了保护民事主体的合法权益")
        assert match and match.group(1) == "一" and match.group(3).startswith("为了")

    def test_article_with_suffix(self):
        match = ARTICLE_RE.match("第一百三十三条之一　在道路上驾驶机动车")
        assert match and match.group(1) == "一百三十三" and match.group(2) == "之一"


class TestParseLaw:
    def test_skips_table_of_contents(self):
        """目录中的章标题不能被当作正文起点"""
        paragraphs = [
            "中华人民共和国劳动合同法",
            "（2007年6月29日通过）",
            "目　　录",
            "第一章　总　　则",
            "第二章　劳动合同的订立",
            "第一章　总　　则",
            "第一条　为了完善劳动合同制度，明确劳动合同双方当事人的权利和义务。",
            "第二条　中华人民共和国境内的企业适用本法。",
            "第二章　劳动合同的订立",
            "第七条　用人单位自用工之日起即与劳动者建立劳动关系。",
        ]
        articles = parse_law(paragraphs, "中华人民共和国劳动合同法")

        assert [a["article_number"] for a in articles] == ["第一条", "第二条", "第七条"]
        assert articles[0]["chapter"] == "第一章 总 则"
        assert articles[2]["chapter"] == "第二章 劳动合同的订立"

    def test_part_chapter_section_hierarchy(self):
        """民法典式三级结构：编 > 章 > 节"""
        paragraphs = [
            "中华人民共和国民法典",
            "第一编　总　　则",
            "第一章　基本规定",
            "第一条　为了保护民事主体的合法权益。",
            "第二章　自然人",
            "第一节　民事权利能力和民事行为能力",
            "第十三条　自然人从出生时起到死亡时止，具有民事权利能力。",
        ]
        articles = parse_law(paragraphs, "中华人民共和国民法典")

        assert articles[0]["part"] == "第一编 总 则"
        assert articles[0]["chapter"] == "第一章 基本规定"
        assert articles[0]["section"] == ""
        assert articles[0]["chapter_path"] == "第一编 总 则 > 第一章 基本规定"

        assert articles[1]["section"] == "第一节 民事权利能力和民事行为能力"
        assert articles[1]["chapter_path"].endswith("第一节 民事权利能力和民事行为能力")

    def test_multi_paragraph_article_kept_together(self):
        """同一款之间的续段要并入同一条，而不是丢成孤立文本"""
        paragraphs = [
            "第一章　总　　则",
            "第九十七条　本法施行前已依法订立且在本法施行之日存续的劳动合同，继续履行。",
            "本法施行前已建立劳动关系，尚未订立书面劳动合同的，应当自本法施行之日起一个月内订立。",
            "第九十八条　本法自2008年1月1日起施行。",
        ]
        articles = parse_law(paragraphs, "中华人民共和国劳动合同法")

        assert len(articles) == 2
        assert "尚未订立书面劳动合同" in articles[0]["content"]
        assert articles[0]["content"].count("\n") == 1
        assert articles[1]["article_index"] == 98

    def test_article_with_suffix_index(self):
        """刑法「之一」条：article_index 与母条相同，条号保留后缀"""
        paragraphs = [
            "第一章　刑法的任务、基本原则和适用范围",
            "第一百三十三条　违反交通运输管理法规，因而发生重大事故。",
            "第一百三十三条之一　在道路上驾驶机动车追逐竞驶，情节恶劣的。",
        ]
        articles = parse_law(paragraphs, "中华人民共和国刑法")

        assert articles[1]["article_number"] == "第一百三十三条之一"
        assert articles[1]["article_index"] == 133

    def test_raises_when_no_article(self):
        """不是法规正文时应明确报错，而不是静默返回空列表"""
        try:
            parse_law(["这是一段说明文字", "没有任何条号"], "无效文档")
        except ValueError as exc:
            assert "未定位到条号" in str(exc)
        else:
            raise AssertionError("应当抛出 ValueError")
