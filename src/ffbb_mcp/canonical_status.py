"""Machine à états canonique des matchs et détection rigoureuse des conflits de statut.

Garantit qu'aucune rencontre incohérente, contradictoire ou non confirmée
ne contamine les calculs sportifs (bilan, dernier/prochain match, H2H, forme, classement).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from ffbb_mcp.envelope import DataQualityInfo


class CanonicalMatchStatus(StrEnum):
    """Statuts de match canoniques unifiés."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    HALFTIME = "halftime"
    OVERTIME = "overtime"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    FORFEIT_HOME = "forfeit_home"
    FORFEIT_AWAY = "forfeit_away"
    FORFEIT_BOTH = "forfeit_both"
    UNKNOWN_CONFLICT = "unknown_conflict"


class TemporalMatchStatus(StrEnum):
    """État temporel calculé, distinct du statut officiel FFBB."""

    SCHEDULED = "scheduled"
    PRESUMED_IN_PROGRESS = "presumed_in_progress"
    STATUS_UNKNOWN_AFTER_TIPOFF = "status_unknown_after_tipoff"
    LIVE = "live"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNKNOWN_CONFLICT = "unknown_conflict"


@dataclass(frozen=True, slots=True)
class TemporalStatusInfo:
    status: TemporalMatchStatus
    confidence: str
    explanation: str


_PARIS_TZ = ZoneInfo("Europe/Paris")
_PRESUMED_LIVE_WINDOW = timedelta(hours=3)


def derive_temporal_match_status(
    match: dict[str, Any],
    *,
    canonical_status: CanonicalMatchStatus | None = None,
    now: datetime | None = None,
) -> TemporalStatusInfo:
    """Calcule l'état temporel sans altérer le statut officiel normalisé."""
    status = canonical_status or canonicalize_match_status(match)[0]

    if status in (
        CanonicalMatchStatus.LIVE,
        CanonicalMatchStatus.HALFTIME,
        CanonicalMatchStatus.OVERTIME,
    ):
        return TemporalStatusInfo(
            TemporalMatchStatus.LIVE,
            "high",
            "Statut live explicitement remonté par la FFBB.",
        )
    if status in (
        CanonicalMatchStatus.FINAL,
        CanonicalMatchStatus.FORFEIT_HOME,
        CanonicalMatchStatus.FORFEIT_AWAY,
        CanonicalMatchStatus.FORFEIT_BOTH,
    ):
        return TemporalStatusInfo(
            TemporalMatchStatus.FINAL,
            "high",
            "Résultat final ou forfait confirmé par la FFBB.",
        )
    if status == CanonicalMatchStatus.POSTPONED:
        return TemporalStatusInfo(
            TemporalMatchStatus.POSTPONED,
            "high",
            "Report confirmé par la FFBB.",
        )
    if status == CanonicalMatchStatus.CANCELLED:
        return TemporalStatusInfo(
            TemporalMatchStatus.CANCELLED,
            "high",
            "Annulation confirmée par la FFBB.",
        )
    if status == CanonicalMatchStatus.UNKNOWN_CONFLICT:
        return TemporalStatusInfo(
            TemporalMatchStatus.UNKNOWN_CONFLICT,
            "low",
            "Les données FFBB présentent des statuts contradictoires.",
        )

    raw_date = (
        match.get("scheduled_at")
        or match.get("date_rencontre")
        or match.get("date")
        or match.get("date_reelle")
    )
    try:
        # ⚡ Bolt: Fast-path. datetime.fromisoformat() natively supports space separators
        scheduled_at = datetime.fromisoformat(str(raw_date))
    except (TypeError, ValueError):
        scheduled_at = None

    if scheduled_at is None:
        return TemporalStatusInfo(
            TemporalMatchStatus.SCHEDULED,
            "low",
            "Horaire de début indisponible ; statut FFBB conservé.",
        )
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=_PARIS_TZ)

    current_time = now or datetime.now(_PARIS_TZ)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=_PARIS_TZ)
    elapsed = current_time.astimezone(UTC) - scheduled_at.astimezone(UTC)

    if elapsed < timedelta(0):
        return TemporalStatusInfo(
            TemporalMatchStatus.SCHEDULED,
            "high",
            "L'horaire officiel de début n'est pas encore atteint.",
        )

    elapsed_minutes = int(elapsed.total_seconds() // 60)
    if elapsed <= _PRESUMED_LIVE_WINDOW:
        return TemporalStatusInfo(
            TemporalMatchStatus.PRESUMED_IN_PROGRESS,
            "medium",
            f"Horaire de début dépassé de {elapsed_minutes} minute(s) ; "
            "aucune donnée live ni résultat final FFBB disponible.",
        )

    return TemporalStatusInfo(
        TemporalMatchStatus.STATUS_UNKNOWN_AFTER_TIPOFF,
        "low",
        f"Horaire de début dépassé de {elapsed_minutes} minute(s) ; "
        "aucun statut final FFBB disponible après la fenêtre habituelle du match.",
    )


def _parse_int_score(val: Any) -> int | None:
    """Extrait un entier de score ou None."""
    if val is None or val == "" or val == "None" or val == "null":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def canonicalize_match_status(
    raw_match: dict[str, Any] | None,
) -> tuple[CanonicalMatchStatus, DataQualityInfo]:
    """Analyse un match brut et résout son statut canonique avec détection de conflits.

    Retourne :
        (CanonicalMatchStatus, DataQualityInfo)
    """
    if not isinstance(raw_match, dict):
        return (
            CanonicalMatchStatus.UNKNOWN_CONFLICT,
            DataQualityInfo(
                level="conflict",
                issues=["Donnée de match invalide (non-dict)"],
                canonical_status=CanonicalMatchStatus.UNKNOWN_CONFLICT.value,
            ),
        )

    issues: list[str] = []

    # Extraction et normalisation des champs source
    raw_statut = str(
        raw_match.get("statut")
        or raw_match.get("status")
        or raw_match.get("statut_rencontre")
        or ""
    ).strip()
    statut_upper = raw_statut.upper()

    cur_status = str(raw_match.get("current_status") or "").strip().upper()
    match_status = str(raw_match.get("match_status") or "").strip().upper()

    raw_joue = raw_match.get("joue")
    raw_played = raw_match.get("played")
    played_bool = bool(
        raw_joue in (1, "1", True) or raw_played in (1, "1", True, "true", "True")
    )

    score1 = _parse_int_score(
        raw_match.get("score_equipe1")
        if raw_match.get("score_equipe1") is not None
        else raw_match.get("resultatEquipe1")
    )
    score2 = _parse_int_score(
        raw_match.get("score_equipe2")
        if raw_match.get("score_equipe2") is not None
        else raw_match.get("resultatEquipe2")
    )
    has_scores = score1 is not None and score2 is not None

    clock = str(raw_match.get("clock") or "").strip()
    period = raw_match.get("current_period")

    raw_statuses = {
        "statut": raw_statut,
        "current_status": cur_status or None,
        "match_status": match_status or None,
        "played": raw_played,
        "joue": raw_joue,
        "scores": f"{score1} - {score2}" if has_scores else None,
        "clock": clock or None,
        "period": period,
    }

    # -----------------------------------------------------------------------
    # 1. Détection des contradictions directes (CONFLITS MAJEURS)
    # -----------------------------------------------------------------------

    # Conflit 1 : complete + IN_PROGRESS
    if (
        cur_status in ("COMPLETE", "FINISHED", "FINAL")
        and match_status in ("IN_PROGRESS", "LIVE")
    ) or (
        cur_status in ("IN_PROGRESS", "LIVE")
        and match_status in ("COMPLETE", "FINISHED", "FINAL")
    ):
        issues.append(
            f"Statuts source contradictoires : current_status='{cur_status}' et match_status='{match_status}'"
        )

    # Conflit 2 : played=True + scheduled
    if played_bool and (
        "SCHEDULED" in statut_upper
        or "PROGRAMME" in statut_upper
        or cur_status == "SCHEDULED"
        or match_status == "SCHEDULED"
    ):
        issues.append(
            f"Contradiction match joué et programmé : played={played_bool} alors que statut='{raw_statut}'"
        )

    # Conflit 3 : score renseigné + statut scheduled (sans played)
    if (
        has_scores
        and (
            (score1 is not None and score1 >= 0) or (score2 is not None and score2 >= 0)
        )
        and not played_bool
        and (
            "SCHEDULED" in statut_upper
            or cur_status == "SCHEDULED"
            or match_status == "SCHEDULED"
        )
    ):
        issues.append(
            f"Scores renseignés ({score1}-{score2}) alors que le match est déclaré programmé (scheduled)"
        )

    # Conflit 4 : score final + statut live en cours avec chronomètre à 00:00
    if (
        has_scores
        and (
            match_status in ("IN_PROGRESS", "LIVE")
            or cur_status in ("IN_PROGRESS", "LIVE")
        )
        and clock in ("00:00", "0")
        and (cur_status in ("COMPLETE", "FINISHED") or played_bool)
    ):
        issues.append(
            "Match déclaré live mais chronomètre à 00:00 et indicateurs de complétion présents"
        )

    # Conflit 5 : Forfait déclaré mais scores incohérents (ni 20-0, ni 0-20, ni 0-0)
    is_forfeit_declared = (
        "FORFAIT" in statut_upper
        or "FORFEIT" in statut_upper
        or bool(raw_match.get("forfait"))
        or bool(raw_match.get("is_forfeit"))
    )
    if (
        is_forfeit_declared
        and has_scores
        and (score1, score2) not in ((20, 0), (0, 20), (0, 0), (None, None))
    ):
        issues.append(
            f"Forfait déclaré mais score incompatible avec la règle fédérale ({score1}-{score2} au lieu de 20-0 ou 0-20)"
        )

    # Conflit 6 : Annulé avec score final positif
    is_cancelled_declared = (
        "ANNUL" in statut_upper
        or "CANCEL" in statut_upper
        or cur_status == "CANCELLED"
        or match_status == "CANCELLED"
    )
    if (
        is_cancelled_declared
        and has_scores
        and ((score1 is not None and score1 > 0) or (score2 is not None and score2 > 0))
    ):
        issues.append(f"Match déclaré annulé mais score renseigné ({score1}-{score2})")

    # Conflit 7 : Reporté avec statut final
    is_postponed_declared = (
        "REPORT" in statut_upper
        or "POSTPONE" in statut_upper
        or cur_status == "POSTPONED"
        or match_status == "POSTPONED"
    )
    if is_postponed_declared and (
        played_bool or cur_status == "FINAL" or match_status == "FINAL"
    ):
        issues.append("Match déclaré reporté tout en étant marqué comme joué/final")

    # Conflit 8 : Statut programmé (scheduled) alors que current_status ou match_status déclare final/complete
    is_scheduled_declared = (
        "SCHEDULED" in statut_upper
        or "PROGRAMME" in statut_upper
        or cur_status == "SCHEDULED"
        or match_status == "SCHEDULED"
    )
    is_completed_declared = (
        cur_status in ("COMPLETE", "FINISHED", "FINAL")
        or match_status in ("COMPLETE", "FINISHED", "FINAL")
        or "TERMINE" in statut_upper
        or "FINAL" in statut_upper
    )
    if is_scheduled_declared and is_completed_declared:
        issues.append(
            f"Contradiction match programmé et terminé : statut='{raw_statut}', current_status='{cur_status}', match_status='{match_status}'"
        )

    # Conflit 9 : Statut programmé (scheduled) alors que current_status ou match_status déclare live/en cours
    is_live_declared = (
        cur_status in ("LIVE", "IN_PROGRESS")
        or match_status in ("LIVE", "IN_PROGRESS")
        or "DIRECT" in statut_upper
        or "LIVE" in statut_upper
    )
    if is_scheduled_declared and is_live_declared:
        issues.append(
            f"Contradiction match programmé et en cours : statut='{raw_statut}', current_status='{cur_status}', match_status='{match_status}'"
        )

    # Date passée ou future si disponible pour cohérence
    raw_date = str(
        raw_match.get("date_rencontre")
        or raw_match.get("date")
        or raw_match.get("date_reelle")
        or ""
    ).strip()
    match_dt: datetime | None = None
    if raw_date:
        try:
            # ⚡ Bolt: Fast-path. datetime.fromisoformat() natively supports space separators
            match_dt = datetime.fromisoformat(raw_date)
            if match_dt.tzinfo is None:
                match_dt = match_dt.replace(tzinfo=UTC)
        except Exception:
            match_dt = None

    now_utc = datetime.now(UTC)
    if match_dt is not None:
        # Match dans le futur (> 2h après maintenant) mais déclaré final
        if (match_dt - now_utc).total_seconds() > 7200 and played_bool:
            issues.append(
                f"Match programmé dans le futur ({match_dt.isoformat()}) déclaré déjà joué/final"
            )
        # Match passé de plus de 48h déclaré toujours 'live'
        if (now_utc - match_dt).total_seconds() > 172800 and (
            match_status in ("LIVE", "IN_PROGRESS")
            or cur_status in ("LIVE", "IN_PROGRESS")
        ):
            issues.append(
                f"Match joué il y a plus de 48h ({match_dt.isoformat()}) déclaré toujours live"
            )

    # Si un conflit a été détecté : retour UNKNOWN_CONFLICT
    if issues:
        quality = DataQualityInfo(
            level="conflict",
            issues=issues,
            raw_statuses=raw_statuses,
            canonical_status=CanonicalMatchStatus.UNKNOWN_CONFLICT.value,
        )
        return CanonicalMatchStatus.UNKNOWN_CONFLICT, quality

    # -----------------------------------------------------------------------
    # 2. Résolution des statuts canoniques cohérents
    # -----------------------------------------------------------------------

    # A. Forfait
    if is_forfeit_declared:
        if score1 == 20 and score2 == 0:
            canon = CanonicalMatchStatus.FORFEIT_AWAY
        elif score1 == 0 and score2 == 20:
            canon = CanonicalMatchStatus.FORFEIT_HOME
        elif score1 == 0 and score2 == 0:
            canon = CanonicalMatchStatus.FORFEIT_BOTH
        else:
            canon = CanonicalMatchStatus.FORFEIT_AWAY
        return canon, DataQualityInfo(
            level="high",
            issues=[],
            raw_statuses=raw_statuses,
            canonical_status=canon.value,
        )

    # B. Annulé
    if is_cancelled_declared:
        return CanonicalMatchStatus.CANCELLED, DataQualityInfo(
            level="high",
            issues=[],
            raw_statuses=raw_statuses,
            canonical_status=CanonicalMatchStatus.CANCELLED.value,
        )

    # C. Reporté
    if is_postponed_declared:
        return CanonicalMatchStatus.POSTPONED, DataQualityInfo(
            level="high",
            issues=[],
            raw_statuses=raw_statuses,
            canonical_status=CanonicalMatchStatus.POSTPONED.value,
        )

    # D. Terminé / Final (match joué cohérent)
    if (
        cur_status in ("COMPLETE", "FINISHED", "FINAL")
        or match_status in ("COMPLETE", "FINISHED", "FINAL")
        or played_bool
        or "OFFICIEL" in statut_upper
        or "FINAL" in statut_upper
        or "TERMINE" in statut_upper
    ):
        return CanonicalMatchStatus.FINAL, DataQualityInfo(
            level="high",
            issues=[],
            raw_statuses=raw_statuses,
            canonical_status=CanonicalMatchStatus.FINAL.value,
        )

    # E. En cours / Live / Halftime / Overtime
    if (
        cur_status in ("LIVE", "IN_PROGRESS", "EN_COURS")
        or match_status in ("LIVE", "IN_PROGRESS", "EN_COURS")
        or "LIVE" in statut_upper
        or "IN_PROGRESS" in statut_upper
        or "EN_COURS" in statut_upper
    ):
        if (
            "HALFTIME" in statut_upper
            or "MI-TEMPS" in statut_upper
            or period in (2, "2", "HT")
        ):
            canon = CanonicalMatchStatus.HALFTIME
        elif (
            "OVERTIME" in statut_upper
            or "PROLONGATION" in statut_upper
            or "OT" in str(period or "")
        ):
            canon = CanonicalMatchStatus.OVERTIME
        else:
            canon = CanonicalMatchStatus.LIVE

        return canon, DataQualityInfo(
            level="high",
            issues=[],
            raw_statuses=raw_statuses,
            canonical_status=canon.value,
        )

    # F. Programmé / Non commencé
    return CanonicalMatchStatus.SCHEDULED, DataQualityInfo(
        level="high",
        issues=[],
        raw_statuses=raw_statuses,
        canonical_status=CanonicalMatchStatus.SCHEDULED.value,
    )


def is_match_eligible_for_aggregate(
    status: CanonicalMatchStatus | dict[str, Any],
    quality: DataQualityInfo | None = None,
) -> bool:
    """Vérifie si une rencontre est saine et autorisée à figurer dans les agrégats sportifs.

    Accepte soit un statut canonique (avec optionnellement sa DataQualityInfo),
    soit directement le dictionnaire du match.
    Exclut impérativement : UNKNOWN_CONFLICT, CANCELLED, POSTPONED et tout match en conflit.
    """
    if isinstance(status, dict):
        st, q = canonicalize_match_status(status)
        return is_match_eligible_for_aggregate(st, q)

    if status == CanonicalMatchStatus.UNKNOWN_CONFLICT:
        return False
    if quality is not None and quality.level == "conflict":
        return False
    return status not in (
        CanonicalMatchStatus.CANCELLED,
        CanonicalMatchStatus.POSTPONED,
    )
