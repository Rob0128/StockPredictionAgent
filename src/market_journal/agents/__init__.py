"""LLM agents and the shared model factory.

Four agents apply judgement where it is useful:
    news_catalyst — is a candidate's move backed by a real catalyst or noise?
    risk          — challenge the candidates (factor crowding, earnings, evidence).
    committee     — structured final paper-pick decision.
    memory        — propose conservative observations/lessons for tomorrow.
"""
