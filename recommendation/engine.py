"""Rule-based recommendation layer.

The LLM is intentionally not allowed to generate the underlying trading signal.
It only explains the structured action produced here.
"""
from __future__ import annotations

from typing import Any, Dict, List


def recommend(analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not analysis.get("success"):
        return {**analysis, "system_action": "WAIT_FOR_DATA", "confidence": "LOW", "signals": [], "risks": []}

    score = 0
    signals: List[str] = []
    risks: List[str] = []

    ret = analysis.get("return_5d")
    rs = analysis.get("relative_strength_vnindex")
    rs30 = analysis.get("relative_strength_vn30")
    tech_change = analysis.get("technical_score_change")
    rsi = analysis.get("rsi_end")
    macd = analysis.get("macd_end")
    macd_signal = analysis.get("macd_signal_end")
    drawdown = analysis.get("max_drawdown_5d")
    final_score = analysis.get("final_score")

    if ret is not None:
        if ret >= 3:
            score += 2; signals.append(f"Giá tăng {ret:.2f}% trong 5 phiên")
        elif ret <= -3:
            score -= 2; risks.append(f"Giá giảm {abs(ret):.2f}% trong 5 phiên")

    if rs is not None:
        if rs >= 2:
            score += 2; signals.append(f"Mạnh hơn VNIndex {rs:.2f} điểm %")
        elif rs <= -2:
            score -= 2; risks.append(f"Yếu hơn VNIndex {abs(rs):.2f} điểm %")

    if rs30 is not None:
        if rs30 >= 2:
            score += 1; signals.append(f"Mạnh hơn VN30 {rs30:.2f} điểm %")
        elif rs30 <= -2:
            score -= 1; risks.append(f"Yếu hơn VN30 {abs(rs30):.2f} điểm %")

    if tech_change is not None:
        if tech_change >= 5:
            score += 2; signals.append(f"Technical Score cải thiện +{tech_change:.1f}")
        elif tech_change <= -5:
            score -= 2; risks.append(f"Technical Score suy yếu {tech_change:.1f}")

    if macd is not None and macd_signal is not None:
        if macd > macd_signal:
            score += 1; signals.append("MACD đang nằm trên Signal")
        else:
            score -= 1; risks.append("MACD đang nằm dưới Signal")

    if rsi is not None:
        if 45 <= rsi <= 65:
            score += 1; signals.append(f"RSI {rsi:.1f} ở vùng động lượng cân bằng")
        elif rsi >= 70:
            score -= 1; risks.append(f"RSI {rsi:.1f} ở vùng cao, hạn chế mua đuổi")
        elif rsi < 35:
            score -= 1; risks.append(f"RSI {rsi:.1f} cho thấy động lượng yếu")

    if drawdown is not None and drawdown <= -5:
        score -= 1; risks.append(f"Drawdown 5 phiên {drawdown:.2f}%")

    if final_score is not None:
        if final_score >= 80:
            score += 2; signals.append(f"Final Score cao {final_score:.1f}")
        elif final_score < 60:
            score -= 2; risks.append(f"Final Score thấp {final_score:.1f}")

    if score >= 6:
        action = "ACCUMULATE_ON_PULLBACK"
    elif score >= 2:
        action = "HOLD_OR_WATCH"
    elif score <= -5:
        action = "REDUCE_OR_EXIT_REVIEW"
    elif score <= -2:
        action = "CAUTION"
    else:
        action = "WATCH"

    evidence_count = sum(x is not None for x in [ret, rs, tech_change, rsi, macd, final_score])
    confidence = "HIGH" if evidence_count >= 5 and abs(score) >= 4 else "MEDIUM" if evidence_count >= 4 else "LOW"

    return {
        **analysis,
        "system_action": action,
        "confidence": confidence,
        "rule_score": score,
        "signals": signals,
        "risks": risks,
        "disclaimer": "Tín hiệu phục vụ nghiên cứu và hỗ trợ ra quyết định, không phải khuyến nghị đầu tư cá nhân hóa.",
    }
