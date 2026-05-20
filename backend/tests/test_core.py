from __future__ import annotations

from pathlib import Path

from app.schemas import AdAnalysisRequest
from app.services.ad_analysis import analyze_ad
from app.services.deepseek import normalize_copy
from app.services.video import create_srt, split_script


def test_normalize_copy_minimal_payload():
    result = normalize_copy({"title": "测试标题", "script": "这是一段口播。", "tags": "AI,短视频"}, "兜底主题")
    assert result.title == "测试标题"
    assert "口播" in result.script
    assert "AI" in result.tags


def test_split_script_and_srt(tmp_path: Path):
    chunks = split_script("老板们，别再手工剪视频了。现在可以自动生成文案、配音和成片。", max_chars=12)
    assert len(chunks) >= 2
    out = tmp_path / "test.srt"
    create_srt("老板们，别再手工剪视频了。现在可以自动生成文案、配音和成片。", 8, out)
    text = out.read_text(encoding="utf-8")
    assert "00:00:00,000" in text
    assert "-->" in text


def test_ad_analysis_returns_metrics():
    resp = analyze_ad(AdAnalysisRequest(title="老板别再手工剪视频", script="老板们，别再一条视频一条视频手工剪了。这里有真实案例和数据，想了解可以私信咨询。", budget=300, industry="企业服务"))
    assert resp.decision
    assert len(resp.metrics) >= 6
    assert resp.optimization_tips
