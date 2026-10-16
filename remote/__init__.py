"""Fase 15 — Game-PC Agent.

Een kleine, beveiligde server op de game-pc die een expliciet
toegestane set acties op afstand uitvoert voor het brein (JARVIS).

Modules:
    protocol  — berichtformaat + HMAC-authenticatie + replay-bescherming.
    allowlist — de enige acties die remote mogen, met strikte parameters.
"""
