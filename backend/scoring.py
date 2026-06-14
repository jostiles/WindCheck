"""
scoring.py — TAF-to-METAR alignment and accuracy scoring.

This is the most complex module.  The key challenge is "which TAF condition
group was actually forecasting the weather at the moment of each METAR?"

Alignment algorithm (resolve_taf_conditions_at_time)
----------------------------------------------------
A TAF's timeline looks like this (simplified):

  BASE ─────────────────────────────────────────────────────►
              FM₁ ─────────────────────────────────────────►
                          BECMG  [from → to]  (completes)
                     TEMPO [from → to]   (overlay, then reverts)
                                     FM₂ ──────────────────►

For an observation at time T we must:

  1. Walk FM groups chronologically.  The last FM whose start ≤ T wins and
     becomes the "current base epoch".  If no FM precedes T, the BASE is the
     current epoch.

  2. Within the current base epoch, find any BECMG groups whose *start* falls
     inside the epoch:
       a. If becmg.valid_to ≤ T  → BECMG has completed; merge its non-null
          elements into the effective conditions (they become permanent until
          the next FM overrides them).
       b. If becmg.valid_from ≤ T < becmg.valid_to  → BECMG is *in progress*.
          The official ICAO interpretation is that conditions are transitioning
          somewhere between the old and new values; for scoring we use the
          *pre-BECMG* (base epoch) conditions since the transition is still
          underway and the final state is not yet assured.

  3. Find any TEMPO or PROB groups whose window [valid_from, valid_to) contains
     T.  These are *overlays*: they temporarily modify (not replace) the
     effective conditions.  We record whether a TEMPO/PROB was active but score
     the observation against the *base* conditions, not the TEMPO overlay.
     (Optionally, callers can also retrieve the TEMPO conditions for a separate
     analysis of "was the TEMPO justified?")

Rationale for scoring against the base rather than TEMPO
---------------------------------------------------------
TEMPO means "expected for less than half the period, intermittently".  Pilots
and dispatchers treat TEMPOs as a warning, not a guarantee.  If TEMPO IFR
occurs and the base was VFR, the TAF technically did warn of the possibility;
however, a TAF that forecasts base IFR is more accurate than one that relies
on a TEMPO.  Scoring against the base therefore rewards forecasters who commit
to the most likely conditions rather than hedging everything to TEMPO.

Scoring functions
-----------------
  score_ceiling_coverage  Ordered scale (SKC→OVC, rank 0→4); score = 1 − |diff| / 4.
  score_ceiling_altitude  FAA flight-category tier match; score = max(0, 1 − |tier_diff| / 3).
  score_visibility        FAA flight-category tier match; same formula as ceiling altitude.
  score_wind_speed        Percentage error on peak wind (speed or gust); score = max(0, 1 − |err|).
  score_wind_direction    Continuous decay; score = max(0, 1 − diff / 90°).
  score_weather           Severity-weighted F1: each phenomenon weighted by hazard tier.
  overall_score           Unweighted mean of all non-None component scores.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from fetch import TRACKED_PHENOMENA

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sky coverage ordering and weather phenomenon severity weights
# ---------------------------------------------------------------------------

# Ordered from clear to overcast (0 = clear, 4 = fully obscured)
COVERAGE_ORDER: dict[str, int] = {
    'SKC': 0, 'CLR': 0,
    'FEW': 1,
    'SCT': 2,
    'BKN': 3,
    'OVC': 4, 'VV': 4,
}

# Severity weights for significant weather phenomena.
# Higher weight = greater operational impact = missing it hurts more.
PHENOMENON_WEIGHTS: dict[str, float] = {
    'TS':   5.0, 'TSRA': 5.0, 'TSSN': 5.0, 'TSGR': 5.0, 'TSGS': 5.0, 'TSPL': 5.0,
    'FZRA': 4.0, 'FZDZ': 4.0, 'FZSN': 4.0,
    'BLSN': 3.0, 'DRSN': 3.0,
    'SN':   2.0, 'PL':   2.0, 'RA':   2.0, 'FG':   2.0,
    'DZ':   1.0, 'GR':   1.0, 'GS':   1.0,
    'BR':   0.5, 'HZ':   0.5, 'FU':   0.5, 'SA':   0.5, 'DU':   0.5,
}
_DEFAULT_PHENOMENON_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# Type alias for a condition snapshot
# ---------------------------------------------------------------------------

# A "conditions dict" carries the resolved forecast or observed values.
# Keys match TAFPeriod / METAR column names.
Conditions = dict  # typed loosely; keys listed below


def _empty_conditions() -> Conditions:
    return {
        "wind_dir":          None,
        "wind_variable":     False,
        "wind_speed":        None,
        "wind_gust":         None,
        "visibility_sm":     None,
        "visibility_gt":     False,
        "ceiling_ft":        None,
        "ceiling_coverage":  None,
        "weather_phenomena": [],
    }


# ---------------------------------------------------------------------------
# TAF alignment  — the tricky part
# ---------------------------------------------------------------------------

def resolve_taf_conditions_at_time(
    periods: list[dict],
    obs_time: datetime,
    taf_valid_from: datetime,
    taf_valid_to: datetime,
) -> tuple[Optional[Conditions], Optional[Conditions]]:
    """
    Compute the effective TAF forecast conditions at ``obs_time``.

    Parameters
    ----------
    periods        List of period dicts as returned by parse_taf_raw().
                   Each dict must have at minimum the keys:
                   period_type, period_seq, valid_from, valid_to,
                   plus all condition fields.
    obs_time       The METAR observation time (UTC, timezone-aware).
    taf_valid_from TAF overall valid start (used as the BASE period start).
    taf_valid_to   TAF overall valid end.

    Returns
    -------
    (base_conditions, tempo_conditions)
        base_conditions   Effective conditions from BASE/FM + completed BECMGs.
                          None if obs_time is outside the TAF valid window.
        tempo_conditions  Active TEMPO/PROB conditions at obs_time, or None.

    Notes on merging
    ----------------
    BECMG and TEMPO groups are "partial overrides": they only specify the
    elements that change.  A None value in a period dict means "inherit from
    the current base".  The merge() helper applies only non-None overrides.
    """
    # Guard: obs must fall within the TAF valid period
    if obs_time < taf_valid_from or obs_time >= taf_valid_to:
        return None, None

    # Separate and sort each group type
    base_periods  = [p for p in periods if p["period_type"] == "BASE"]
    fm_groups     = sorted(
        [p for p in periods if p["period_type"] == "FM"],
        key=lambda p: _iso(p["valid_from"])
    )
    becmg_groups  = sorted(
        [p for p in periods if p["period_type"] == "BECMG"],
        key=lambda p: _iso(p["valid_from"])
    )
    tempo_groups  = sorted(
        [p for p in periods if p["period_type"] in ("TEMPO", "PROB")],
        key=lambda p: _iso(p["valid_from"])
    )

    if not base_periods:
        logger.warning("TAF has no BASE period — cannot align")
        return None, None

    # ── Step 1: Find the current base epoch (BASE or latest FM before T) ──
    #
    # Each FM completely replaces all conditions from its start time forward.
    # We walk FM groups chronologically and keep the last one that has started.
    current_epoch: dict = base_periods[0]
    epoch_start:   datetime = taf_valid_from

    for fm in fm_groups:
        fm_start = _iso(fm["valid_from"])
        if fm_start <= obs_time:
            current_epoch = fm
            epoch_start   = fm_start
        else:
            break  # FM groups are sorted; no point continuing

    # The current epoch ends at the start of the next FM (or TAF end)
    epoch_end: datetime = taf_valid_to
    for fm in fm_groups:
        fm_start = _iso(fm["valid_from"])
        if fm_start > epoch_start:
            epoch_end = fm_start
            break

    # ── Step 2: Apply completed BECMG groups within the current epoch ──
    #
    # A BECMG "belongs" to the current epoch if its valid_from falls inside
    # [epoch_start, epoch_end).  Multiple BECMGs can chain within one epoch.
    #
    # Order matters: BECMGs that completed earlier may themselves be partially
    # overridden by later BECMGs or the next FM.  We apply them in sequence.
    effective = _clone(current_epoch)

    in_becmg_transition = False  # will be True if we're mid-BECMG

    for becmg in becmg_groups:
        b_from = _iso(becmg["valid_from"])
        b_to   = _iso(becmg["valid_to"])

        # Only consider BECMGs that start inside the current epoch
        if b_from < epoch_start or b_from >= epoch_end:
            continue

        if b_to <= obs_time:
            # BECMG has fully completed: merge its conditions into the base.
            # Non-None fields in the BECMG override effective; None fields
            # are left unchanged (they continue from the epoch base).
            _merge(effective, becmg)

        elif b_from <= obs_time < b_to:
            # BECMG is currently in progress.
            # Official interpretation: conditions are "becoming" — they may be
            # anywhere between the old and new values.  We conservatively keep
            # the pre-BECMG conditions (effective is already correct here since
            # we haven't called _merge yet) and set a flag for the caller.
            in_becmg_transition = True
            # Note: we do NOT merge; the transition is not yet complete.

    effective["_in_becmg_transition"] = in_becmg_transition

    # ── Step 3: Identify any active TEMPO / PROB overlay ──
    #
    # TEMPO/PROB groups that (a) start inside the current epoch and (b) whose
    # window [valid_from, valid_to) contains obs_time are "active".
    # We return the first active one found (they should not overlap in a
    # well-formed TAF; if they do, we take the highest-priority one, i.e.
    # the one with the lowest period_seq).
    active_tempo: Optional[dict] = None
    for tp in tempo_groups:
        t_from = _iso(tp["valid_from"])
        t_to   = _iso(tp["valid_to"])

        # Must start within the current epoch
        if t_from < epoch_start or t_from >= epoch_end:
            continue
        # Must be active at obs_time
        if t_from <= obs_time < t_to:
            active_tempo = tp
            break  # take the first (lowest period_seq) match

    # Build the tempo conditions snapshot (merged on top of effective base)
    tempo_conditions: Optional[Conditions] = None
    if active_tempo is not None:
        tempo_conditions = _clone(effective)
        _merge(tempo_conditions, active_tempo)

    return effective, tempo_conditions


# ---------------------------------------------------------------------------
# Condition helpers
# ---------------------------------------------------------------------------

def _iso(dt_str: str) -> datetime:
    """Parse ISO-8601 datetime string to UTC-aware datetime."""
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clone(period: dict) -> Conditions:
    """Snapshot a period's condition fields into a plain dict."""
    return {
        "wind_dir":          period.get("wind_dir"),
        "wind_variable":     bool(period.get("wind_variable", False)),
        "wind_speed":        period.get("wind_speed"),
        "wind_gust":         period.get("wind_gust"),
        "visibility_sm":     period.get("visibility_sm"),
        "visibility_gt":     bool(period.get("visibility_gt", False)),
        "ceiling_ft":        period.get("ceiling_ft"),
        "ceiling_coverage":  period.get("ceiling_coverage"),
        "weather_phenomena": list(period.get("weather_phenomena") or []),
    }


def _merge(base: Conditions, override: dict) -> None:
    """
    In-place merge of ``override`` fields into ``base``.

    Only non-None fields in the override dict are applied.  This models the
    TAF convention that BECMG/TEMPO groups only specify the elements that
    change; omitted elements continue from the current base.

    Weather phenomena are *replaced* (not merged) when the override specifies
    a non-empty list, because a BECMG that clears weather explicitly resets
    the phenomenon list (often signalled by "NSW" — nil significant weather —
    but sometimes simply by omitting the weather token).
    """
    for key in ("wind_dir", "wind_speed", "wind_gust", "visibility_sm",
                "ceiling_ft", "ceiling_coverage"):
        val = override.get(key)
        if val is not None:
            base[key] = val

    # Boolean flags: only override if the source explicitly set True
    if override.get("wind_variable"):
        base["wind_variable"] = True
    if override.get("visibility_gt"):
        base["visibility_gt"] = True

    # Weather: replace if the override has a non-None (even empty) list
    wx = override.get("weather_phenomena")
    if wx is not None:
        base["weather_phenomena"] = list(wx)


# ---------------------------------------------------------------------------
# Individual parameter scoring functions
# ---------------------------------------------------------------------------

def _ceiling_category(ceiling_ft: Optional[int]) -> int:
    """
    Map a ceiling altitude to an FAA flight-category tier.

    Tier  Category  Ceiling
    ----  --------  -------
      3   VFR       ≥ 3,000 ft AGL  (also used when no ceiling is reported)
      2   MVFR      1,000 – 2,999 ft
      1   IFR         500 –   999 ft
      0   LIFR            < 500 ft
    """
    if ceiling_ft is None:
        return 3  # no ceiling → VFR
    if ceiling_ft < 500:
        return 0  # LIFR
    if ceiling_ft < 1000:
        return 1  # IFR
    if ceiling_ft < 3000:
        return 2  # MVFR
    return 3  # VFR


def _visibility_category(vis_sm: Optional[float]) -> int:
    """
    Map a visibility value (statute miles) to an FAA flight-category tier.

    Tier  Category  Visibility
    ----  --------  ----------
      3   VFR       ≥ 5 SM  (also used when visibility is unknown)
      2   MVFR      3 – 4.99 SM
      1   IFR       1 – 2.99 SM
      0   LIFR          < 1 SM
    """
    if vis_sm is None:
        return 3  # unknown → assume VFR
    if vis_sm < 1.0:
        return 0  # LIFR
    if vis_sm < 3.0:
        return 1  # IFR
    if vis_sm < 5.0:
        return 2  # MVFR
    return 3  # VFR


def score_ceiling_coverage(
    forecast_coverage: Optional[str],
    observed_coverage: Optional[str],
) -> float:
    """
    Score sky coverage using an ordered categorical scale.

    Coverage types are ranked from clear to fully obscured:
      SKC / CLR = 0  (clear)
      FEW        = 1
      SCT        = 2
      BKN        = 3
      OVC / VV   = 4  (overcast / vertical visibility)

    Unknown or absent coverage is treated as clear (rank 0).

    Score formula:  1 − |forecast_rank − observed_rank| / 4

    Examples:
      BKN vs BKN  → |3 − 3| / 4 = 1.00
      BKN vs OVC  → |3 − 4| / 4 = 0.75
      SCT vs OVC  → |2 − 4| / 4 = 0.50
      FEW vs OVC  → |1 − 4| / 4 = 0.25
      SKC vs OVC  → |0 − 4| / 4 = 0.00
    """
    fc = COVERAGE_ORDER.get(forecast_coverage or '', 0)
    ob = COVERAGE_ORDER.get(observed_coverage or '', 0)
    return 1.0 - abs(fc - ob) / 4.0


def score_ceiling_altitude(
    forecast_ceiling: Optional[int],
    observed_ceiling: Optional[int],
) -> float:
    """
    Score ceiling altitude by FAA flight-category tier preservation.

    Both the forecast and observed ceiling are mapped to a flight-category
    tier (0 = LIFR, 1 = IFR, 2 = MVFR, 3 = VFR).  A reported ceiling of
    None means no ceiling layer — treated as VFR (tier 3).

    Score formula:  max(0, 1 − |forecast_tier − observed_tier| / 3)

    Tier distances and scores:
      Same tier      → 1.00  (e.g. both IFR)
      1 tier apart   → 0.67  (e.g. IFR vs MVFR)
      2 tiers apart  → 0.33  (e.g. LIFR vs MVFR)
      3 tiers apart  → 0.00  (e.g. LIFR vs VFR)

    Rationale: a 900 ft ceiling vs a 1,100 ft ceiling is an operationally
    trivial difference (both IFR); a 900 ft ceiling vs "no ceiling" is not.
    The tier system captures operational impact rather than raw altitude error.
    """
    fc_cat = _ceiling_category(forecast_ceiling)
    ob_cat = _ceiling_category(observed_ceiling)
    return max(0.0, 1.0 - abs(fc_cat - ob_cat) / 3.0)


def score_visibility(
    forecast_vis: Optional[float],
    observed_vis: Optional[float],
    forecast_gt: bool = False,
) -> Optional[float]:
    """
    Score visibility by FAA flight-category tier preservation.

    Both sides are mapped to a flight-category tier (0 = LIFR, 1 = IFR,
    2 = MVFR, 3 = VFR).

    P6SM handling: when ``forecast_gt`` is True the TAF is predicting
    *at least* ``forecast_vis`` SM (a lower bound).  Since that lower bound
    is ≥ 6 SM, the forecast tier is always VFR (tier 3).

    Returns None when the observed visibility is unavailable (no observation
    to compare against).  An unknown forecast visibility is treated as VFR.

    Score formula:  max(0, 1 − |forecast_tier − observed_tier| / 3)

    Tier distances and scores are the same as ceiling altitude scoring.
    """
    if observed_vis is None:
        return None
    fc_cat = 3 if (forecast_gt or forecast_vis is None) else _visibility_category(forecast_vis)
    ob_cat = _visibility_category(observed_vis)
    return max(0.0, 1.0 - abs(fc_cat - ob_cat) / 3.0)


def score_wind_speed(
    forecast_speed: Optional[int],
    observed_speed: Optional[int],
    forecast_gust: Optional[int] = None,
    observed_gust: Optional[int] = None,
) -> Optional[float]:
    """
    Score wind speed accuracy using percentage-based error on peak wind.

    Peak wind magnitude for each side is defined as:
      peak = max(speed, gust)  when a gust is reported
      peak = speed             otherwise

    This means a TAF that calls for gusts to 35 kt is held to 35 kt, and
    a METAR reporting gusts to 40 kt is compared against that 35 kt peak.
    The gust — not the sustained speed — is the operationally relevant
    magnitude when one is present.

    Score formula:
      error = |forecast_peak − observed_peak| / max(forecast_peak, observed_peak, 1)
      score = max(0, 1 − error)

    A percentage-based denominator means a 10 kt error on a 10 kt wind
    (100% error, score ≈ 0.0) is penalised far more than a 10 kt error on
    a 50 kt wind (20% error, score ≈ 0.80).  The floor of 1 in the
    denominator prevents division by zero on calm-wind observations.

    Returns None if either speed is unavailable.
    """
    if forecast_speed is None or observed_speed is None:
        return None
    fc_peak = max(forecast_speed, forecast_gust or 0)
    ob_peak = max(observed_speed, observed_gust or 0)
    denom = max(fc_peak, ob_peak, 1)
    error = abs(fc_peak - ob_peak) / denom
    return max(0.0, 1.0 - error)


def score_wind_direction(
    forecast_dir: Optional[int],
    observed_dir: Optional[int],
    forecast_variable: bool = False,
    observed_variable: bool = False,
) -> Optional[float]:
    """
    Score wind direction accuracy using continuous angular decay.

    The score decays linearly from 1.0 at 0° error to 0.0 at 90° error,
    then stays at 0.0 for any larger disagreement:

      score = max(0, 1 − diff / 90)

    Circular arithmetic is used so that 350° vs 010° = 20°, not 340°.

    The 90° zero-point reflects that a right-angle wind error (e.g. a
    southwest wind forecast against a northwest observed wind) represents a
    fundamentally wrong forecast — a pilot planning crosswind corrections
    would be pointing the wrong way entirely.

    Variable wind (VRB) handling:
      - Both VRB → 1.0 (agreement).
      - One VRB, one directional → None (not comparable).
      - Either value missing → None.
    """
    if forecast_variable and observed_variable:
        return 1.0
    if forecast_variable or observed_variable:
        return None
    if forecast_dir is None or observed_dir is None:
        return None
    diff = abs(forecast_dir - observed_dir) % 360
    if diff > 180:
        diff = 360 - diff
    return max(0.0, 1.0 - diff / 90.0)


def _normalize_phenomena(weather_list: list[str]) -> set[str]:
    """
    Reduce raw weather-group tokens to a set of base phenomenon codes.

    Examples:
      ["-RA", "+TSRA", "FG"]  →  {"RA", "TS", "FG"}
      ["FZRA"]                →  {"FZRA"}
      ["BR"]                  →  {"BR"}

    We keep FZRA/FZDZ/BLSN as compound codes because they represent
    meaningfully different hazards from their components (RA, DZ, SN).
    """
    result: set[str] = set()
    for token in weather_list:
        upper = token.upper().lstrip("+-").lstrip("VC")
        # Compound hazards to keep intact
        for compound in ("FZRA", "FZDZ", "FZSN", "BLSN", "DRSN", "TSRA",
                         "TSSN", "TSGR", "TSGS", "TSPL"):
            if compound in upper:
                result.add(compound)
                # Also add TS if the compound has it
                if compound.startswith("TS"):
                    result.add("TS")
                break
        else:
            # Strip descriptor (FZ, SH, BL, DR, MI, BC, PR) and intensity
            for desc in ("FZ", "SH", "BL", "DR", "MI", "BC", "PR", "TS"):
                if upper.startswith(desc):
                    upper = upper[len(desc):]
                    if desc == "TS":
                        result.add("TS")
                    break
            # What remains is the raw phenomenon code
            if upper in TRACKED_PHENOMENA:
                result.add(upper)
    return result


def score_weather_phenomena(
    forecast_wx: list[str],
    observed_wx: list[str],
) -> tuple[Optional[float], Optional[float]]:
    """
    Score weather-phenomenon accuracy as severity-weighted precision and recall.

    Each tracked phenomenon is assigned a severity weight that reflects its
    operational hazard (see PHENOMENON_WEIGHTS).  Phenomena not in the table
    receive a default weight of 1.0.

    Weighted precision = Σ weight(TP) / (Σ weight(TP) + Σ weight(FP))
    Weighted recall    = Σ weight(TP) / (Σ weight(TP) + Σ weight(FN))

    where TP = correctly forecast phenomena, FP = forecast but not observed,
    FN = observed but not forecast.

    This means missing a thunderstorm (weight 5) hurts 10× more than missing
    light mist (weight 0.5) in both precision and recall calculations.

    Returns (None, None) when neither forecast nor observation has any
    significant weather.  When one side is empty:
      - Forecast only → recall = None, precision penalised for false alarm.
      - Observed only → precision = None, recall penalised for miss.

    The overall wx_component in score_metar_vs_taf combines these into an
    F1 score (harmonic mean) when both are available.
    """
    fc_set = _normalize_phenomena(forecast_wx or [])
    ob_set = _normalize_phenomena(observed_wx or [])

    if not fc_set and not ob_set:
        return None, None

    def _w(p: str) -> float:
        return PHENOMENON_WEIGHTS.get(p, _DEFAULT_PHENOMENON_WEIGHT)

    tp_weight = sum(_w(p) for p in fc_set & ob_set)
    fp_weight = sum(_w(p) for p in fc_set - ob_set)
    fn_weight = sum(_w(p) for p in ob_set - fc_set)

    precision: Optional[float]
    recall:    Optional[float]

    if fc_set:
        denom = tp_weight + fp_weight
        precision = tp_weight / denom if denom > 0 else 0.0
    else:
        precision = None

    if ob_set:
        denom = tp_weight + fn_weight
        recall = tp_weight / denom if denom > 0 else 0.0
    else:
        recall = None

    return precision, recall


_FLIGHT_CATS = ["LIFR", "IFR", "MVFR", "VFR"]

def flight_category(ceiling_ft: Optional[int], vis_sm: Optional[float]) -> str:
    """
    Derive FAA flight category from ceiling and visibility (OR logic).
    NULL ceiling = no ceiling = VFR ceiling tier.
    NULL visibility = unknown = VFR visibility tier.
    The worse of the two elements determines the category.
    """
    ceil_tier = _ceiling_category(ceiling_ft)   # 0=LIFR … 3=VFR
    vis_tier  = _visibility_category(vis_sm)    # 0=LIFR … 3=VFR
    return _FLIGHT_CATS[min(ceil_tier, vis_tier)]


def _overall_score(scores: list[Optional[float]]) -> Optional[float]:
    """Unweighted mean of all non-None scores.  None if all are None."""
    valid = [s for s in scores if s is not None]
    return sum(valid) / len(valid) if valid else None


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def score_metar_vs_taf(
    metar: dict,
    taf: dict,
    periods: list[dict],
) -> Optional[dict]:
    """
    Compute all accuracy scores for one METAR observation against one TAF.

    Parameters
    ----------
    metar    Decoded METAR dict (keys match METAR model columns).
    taf      TAF header dict (keys: valid_from, valid_to, id, airport_icao).
    periods  List of TAFPeriod dicts for this TAF.

    Returns
    -------
    A dict matching the ForecastScore model columns, or None if the METAR
    falls outside the TAF's valid period.

    Workflow
    --------
    1. Parse the observation time and check it falls inside the TAF window.
    2. Compute forecast_hour_offset (hours from TAF valid_from to obs_time).
    3. Call resolve_taf_conditions_at_time() to get the aligned forecast.
    4. Run each scoring function against (forecast_conditions, metar).
    5. Compute the overall score as the mean of all non-None scores.
    """
    obs_time_str  = metar.get("observation_time")
    taf_from_str  = taf.get("valid_from")
    taf_to_str    = taf.get("valid_to")

    if not obs_time_str or not taf_from_str or not taf_to_str:
        return None

    obs_time = _iso(obs_time_str)
    taf_from = _iso(taf_from_str)
    taf_to   = _iso(taf_to_str)

    # ── Alignment ──
    base_cond, tempo_cond = resolve_taf_conditions_at_time(
        periods, obs_time, taf_from, taf_to
    )
    if base_cond is None:
        return None  # METAR outside TAF window

    # Forecast hour offset: how far into the valid period is this observation?
    delta_h = (obs_time - taf_from).total_seconds() / 3600.0

    # ── Per-parameter scores ──
    fc_ceil_cov = base_cond.get("ceiling_coverage")
    fc_ceil_ft  = base_cond.get("ceiling_ft")
    fc_vis   = base_cond.get("visibility_sm")
    fc_vis_gt = bool(base_cond.get("visibility_gt", False))
    fc_wspd  = base_cond.get("wind_speed")
    fc_gust  = base_cond.get("wind_gust")
    fc_wdir  = base_cond.get("wind_dir")
    fc_wvar  = base_cond.get("wind_variable", False)
    fc_wx    = base_cond.get("weather_phenomena") or []

    ob_ceil_cov = metar.get("ceiling_coverage")
    ob_ceil_ft  = metar.get("ceiling_ft")
    ob_vis   = metar.get("visibility_sm")
    ob_wspd  = metar.get("wind_speed")
    ob_gust  = metar.get("wind_gust")
    ob_wdir  = metar.get("wind_dir")
    ob_wvar  = bool(metar.get("wind_variable", False))
    ob_wx    = metar.get("weather_phenomena") or []

    ceil_cov_score = score_ceiling_coverage(fc_ceil_cov, ob_ceil_cov)
    ceil_alt_score = score_ceiling_altitude(fc_ceil_ft, ob_ceil_ft)
    vis_score  = score_visibility(fc_vis, ob_vis, fc_vis_gt)
    spd_score  = score_wind_speed(fc_wspd, ob_wspd, fc_gust, ob_gust)
    dir_score  = score_wind_direction(fc_wdir, ob_wdir, fc_wvar, ob_wvar)
    wx_prec, wx_rec = score_weather_phenomena(fc_wx, ob_wx)

    # Absolute differences
    _cov_ord = {"SKC": 0, "FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4, "VV": 4}
    ceil_cov_diff: int = abs(
        _cov_ord.get(fc_ceil_cov or "SKC", 0) - _cov_ord.get(ob_ceil_cov or "SKC", 0)
    )
    ceil_alt_diff: Optional[int] = (
        abs(fc_ceil_ft - ob_ceil_ft)
        if fc_ceil_ft is not None and ob_ceil_ft is not None and fc_ceil_cov and ob_ceil_cov
        else None
    )
    vis_diff: Optional[float] = (
        round(abs(fc_vis - ob_vis), 2) if fc_vis is not None and ob_vis is not None else None
    )
    spd_diff: Optional[int] = (
        abs(fc_wspd - ob_wspd) if fc_wspd is not None and ob_wspd is not None else None
    )
    _raw_dir = (
        abs(fc_wdir - ob_wdir)
        if fc_wdir is not None and ob_wdir is not None and not fc_wvar and not ob_wvar
        else None
    )
    dir_diff: Optional[int] = min(_raw_dir, 360 - _raw_dir) if _raw_dir is not None else None

    # overall: average ceiling_coverage + ceiling_altitude + visibility +
    # wind_speed + wind_dir.  wx_precision/wx_recall are stored for future
    # use but intentionally excluded from the overall score.
    wx_component: Optional[float] = None
    if wx_prec is not None and wx_rec is not None:
        denom = wx_prec + wx_rec
        wx_component = (2 * wx_prec * wx_rec / denom) if denom > 0 else 0.0
    elif wx_prec is not None:
        wx_component = wx_prec
    elif wx_rec is not None:
        wx_component = wx_rec

    overall = _overall_score([
        ceil_cov_score, ceil_alt_score, vis_score, spd_score, dir_score
    ])

    return {
        "airport_icao":          metar.get("airport_icao") or taf.get("icao"),
        "forecast_hour_offset":  round(delta_h, 2),
        "ceiling_coverage_score": ceil_cov_score,
        "ceiling_altitude_score": ceil_alt_score,
        "visibility_score":       vis_score,
        "wind_speed_score":       spd_score,
        "wind_dir_score":         dir_score,
        "wx_precision":           wx_prec,
        "wx_recall":              wx_rec,
        "overall_score":          overall,
        "tempo_active":           1 if tempo_cond is not None else 0,
        "ceiling_coverage_diff":  ceil_cov_diff,
        "ceiling_altitude_diff":  ceil_alt_diff,
        "visibility_diff":        vis_diff,
        "wind_speed_diff":        spd_diff,
        "wind_dir_diff":          dir_diff,
        "fc_flight_category":     flight_category(fc_ceil_ft, fc_vis),
        "ob_flight_category":     flight_category(ob_ceil_ft, ob_vis),
    }


# ---------------------------------------------------------------------------
# Airport-level pipeline
# ---------------------------------------------------------------------------

def find_best_taf(tafs: list[dict], obs_time: datetime) -> Optional[dict]:
    """
    Select the TAF whose valid period covers ``obs_time`` and was issued most
    recently before the observation.

    When multiple TAFs (including amendments) are available, we prefer the
    one that was issued latest while still predating the observation.  This
    mirrors operational use: dispatchers use the most current TAF available.

    Parameters
    ----------
    tafs      List of TAF header dicts sorted by issue_time ascending.
    obs_time  The METAR observation time.

    Returns
    -------
    The best TAF dict, or None if no TAF covers the observation time.
    """
    best: Optional[dict] = None
    for taf in tafs:
        taf_from = _iso(taf["valid_from"])
        taf_to   = _iso(taf["valid_to"])
        issue_dt = _iso(taf["issue_time"])

        if taf_from <= obs_time < taf_to and issue_dt <= obs_time:
            # Among all covering TAFs, prefer the one issued latest
            if best is None or issue_dt > _iso(best["issue_time"]):
                best = taf

    return best


def process_airport(
    icao: str,
    metars: list[dict],
    tafs: list[dict],
) -> list[dict]:
    """
    Generate ForecastScore dicts for every METAR at ``icao``.

    For each METAR observation:
      1. Find the best covering TAF (find_best_taf).
      2. Align the METAR to the appropriate TAF period.
      3. Compute per-parameter accuracy scores.

    Parameters
    ----------
    icao    Station identifier (informational; already embedded in each dict).
    metars  Decoded METAR dicts for the station.
    tafs    Parsed TAF dicts for the station (with embedded period lists).

    Returns
    -------
    List of ForecastScore dicts ready for insertion into the database.
    """
    score_rows: list[dict] = []

    for metar in metars:
        obs_str = metar.get("observation_time")
        if not obs_str:
            continue
        obs_time = _iso(obs_str)

        taf = find_best_taf(tafs, obs_time)
        if taf is None:
            logger.debug(
                "No covering TAF for %s observation at %s", icao, obs_str
            )
            continue

        score = score_metar_vs_taf(metar, taf, taf.get("periods", []))
        if score is None:
            continue

        # Attach FK references (actual IDs are assigned by the DB layer)
        score["_metar_obs_time"] = obs_str
        score["_taf_issue_time"] = taf.get("issue_time")
        score_rows.append(score)

    logger.info(
        "Scored %d/%d observations for %s", len(score_rows), len(metars), icao
    )
    return score_rows
