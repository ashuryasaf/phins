"""Published ADL 3 remaining-life expectancy.

Source columns are age, man, woman, average, and the published sex gap.
``average_years`` is the published average. It is not (man + woman) / 2.
``female_excess_pct`` is the published percent gap, not a premium load.
On a few ages that published percent differs by one point from
round((woman - man) / man) because man and woman are already rounded.
Repeated ages are stored as published, including the copies at 100–101
and the flat run at 103–107.
This table does not price q(x), i(x), or the ADL 10 mortality multiplier.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

TABLE_NAME = 'adl3_disabled_life_expectancy'
AGE_MIN = 1
AGE_MAX = 110

# age, male_years, female_years, average_years, female_excess_pct
_ROWS = (
    (1, 9.12, 9.22, 9.17212764, 1),
    (2, 9.2, 9.3, 9.245869716, 1),
    (3, 7.61, 9.38, 8.495946757, 23),
    (4, 7.61, 9.39, 8.499549016, 23),
    (5, 7.58, 9.37, 8.475575733, 23),
    (6, 7.55, 9.34, 8.445733435, 24),
    (7, 7.51, 9.3, 8.403629261, 24),
    (8, 7.46, 9.23, 8.343506893, 24),
    (9, 7.4, 9.17, 8.283267869, 24),
    (10, 7.33, 9.09, 8.214374552, 24),
    (11, 7.28, 9.02, 8.147172452, 24),
    (12, 7.22, 8.96, 8.087755032, 24),
    (13, 7.17, 8.9, 8.033801591, 24),
    (14, 7.14, 8.87, 8.006334922, 24),
    (15, 7.12, 8.86, 7.990708081, 24),
    (16, 7.12, 8.86, 7.989847153, 25),
    (17, 7.12, 8.91, 8.012274293, 25),
    (18, 7.13, 8.96, 8.048402893, 26),
    (19, 6.83, 8.36, 7.596250926, 22),
    (20, 6.47, 7.68, 7.074708114, 19),
    (21, 6.16, 8.58, 7.372475606, 39),
    (22, 5.87, 7.95, 6.908106146, 35),
    (23, 5.58, 7.36, 6.471955965, 32),
    (24, 5.57, 7.16, 6.364739576, 29),
    (25, 5.56, 6.98, 6.270258426, 26),
    (26, 5.55, 6.83, 6.187365166, 23),
    (27, 5.47, 6.63, 6.048427183, 21),
    (28, 5.4, 6.44, 5.920523469, 19),
    (29, 5.33, 6.27, 5.798593366, 18),
    (30, 5.25, 6.12, 5.685014305, 16),
    (31, 5.18, 5.97, 5.576870382, 15),
    (32, 5.11, 5.84, 5.473921814, 14),
    (33, 5.04, 5.72, 5.37789543, 13),
    (34, 5.0, 5.63, 5.311859932, 13),
    (35, 4.95, 5.54, 5.248615017, 12),
    (36, 4.91, 5.47, 5.190121548, 11),
    (37, 4.87, 5.4, 5.134264384, 11),
    (38, 4.83, 5.33, 5.079857262, 10),
    (39, 4.78, 5.27, 5.028872646, 10),
    (40, 4.77, 5.24, 5.00444442, 10),
    (41, 4.76, 5.2, 4.98320071, 9),
    (42, 4.75, 5.17, 4.959290898, 9),
    (43, 4.73, 5.14, 4.935424056, 9),
    (44, 4.71, 5.11, 4.912155651, 9),
    (45, 4.68, 5.09, 4.886694474, 9),
    (46, 4.68, 5.07, 4.878229726, 8),
    (47, 4.68, 5.06, 4.868690086, 8),
    (48, 4.65, 5.05, 4.846861593, 9),
    (49, 4.55, 5.05, 4.803358193, 11),
    (50, 4.46, 5.06, 4.76285216, 13),
    (51, 4.38, 5.07, 4.726251695, 16),
    (52, 4.3, 5.1, 4.699242529, 19),
    (53, 4.24, 5.12, 4.678305225, 21),
    (54, 4.23, 5.12, 4.67834577, 21),
    (55, 4.23, 5.14, 4.686146006, 21),
    (56, 4.24, 5.14, 4.689584552, 21),
    (57, 4.24, 5.15, 4.694816526, 22),
    (58, 4.23, 5.16, 4.695769753, 22),
    (59, 4.27, 5.24, 4.756396139, 23),
    (60, 4.31, 5.32, 4.814741185, 23),
    (61, 4.35, 5.39, 4.870145911, 24),
    (62, 4.39, 5.46, 4.925651324, 24),
    (63, 4.46, 5.54, 5.000039087, 24),
    (64, 4.45, 5.55, 4.999102426, 25),
    (65, 4.41, 5.55, 4.980276874, 26),
    (66, 4.37, 5.55, 4.9593667, 27),
    (67, 4.33, 5.54, 4.936747955, 28),
    (68, 4.28, 5.52, 4.897998219, 29),
    (69, 4.22, 5.59, 4.906238671, 32),
    (70, 4.17, 5.66, 4.912557052, 36),
    (71, 4.1, 5.7, 4.90042831, 39),
    (72, 4.04, 5.73, 4.884551282, 42),
    (73, 3.96, 5.76, 4.860361341, 45),
    (74, 3.88, 5.68, 4.777832975, 46),
    (75, 3.81, 5.61, 4.709244341, 47),
    (76, 3.74, 5.54, 4.64114864, 48),
    (77, 3.67, 5.45, 4.561224428, 48),
    (78, 3.59, 5.34, 4.464386704, 49),
    (79, 3.51, 5.24, 4.374848213, 50),
    (80, 3.42, 5.15, 4.287407711, 51),
    (81, 3.34, 5.06, 4.20033764, 51),
    (82, 3.26, 4.96, 4.113294446, 52),
    (83, 3.18, 4.87, 4.026646488, 53),
    (84, 3.1, 4.76, 3.932326647, 54),
    (85, 3.02, 4.66, 3.8420652, 54),
    (86, 2.95, 4.56, 3.752862314, 55),
    (87, 2.88, 4.46, 3.6666035, 55),
    (88, 2.81, 4.35, 3.579504797, 55),
    (89, 2.74, 4.2, 3.47378104, 53),
    (90, 2.68, 4.04, 3.361828286, 51),
    (91, 2.62, 3.89, 3.253515387, 48),
    (92, 2.56, 3.73, 3.144270692, 45),
    (93, 2.5, 3.56, 3.033533979, 42),
    (94, 2.45, 3.44, 2.943190828, 40),
    (95, 2.39, 3.31, 2.848531081, 38),
    (96, 2.34, 3.17, 2.755839443, 36),
    (97, 2.28, 3.05, 2.66401321, 33),
    (98, 2.23, 2.92, 2.575906918, 31),
    (99, 2.17, 2.81, 2.490826055, 29),
    (100, 2.23, 2.92, 2.575906918, 31),
    (101, 2.17, 2.81, 2.490826055, 29),
    (102, 2.18, 2.86, 2.519540473, 31),
    (103, 2.13, 2.8, 2.463197767, 31),
    (104, 2.13, 2.8, 2.463197767, 31),
    (105, 2.13, 2.8, 2.463197767, 31),
    (106, 2.13, 2.8, 2.463197767, 31),
    (107, 2.13, 2.8, 2.463197767, 31),
    (108, 1.07, 1.39, 1.227388957, 30),
    (109, 0.72, 0.95, 0.836983138, 33),
    (110, 0.72, 0.95, 0.836983138, 33),
)


def adl3_disabled_life_expectancy_rows() -> List[Dict[str, Any]]:
    """Deep copy of the published rows. Callers may edit the copy."""
    return [
        {
            'age': age,
            'male_years': male,
            'female_years': female,
            'average_years': average,
            'female_excess_pct': excess,
        }
        for age, male, female, average, excess in _ROWS
    ]


def adl3_row_at(rows: Optional[List[Dict[str, Any]]], age: int) -> Optional[Dict[str, Any]]:
    """Exact-age lookup. A missing or incomplete row stays None."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get('age')) != int(age):
                continue
        except (TypeError, ValueError):
            continue
        try:
            male = float(row.get('male_years'))
            female = float(row.get('female_years'))
            average = float(row.get('average_years'))
        except (TypeError, ValueError):
            return None
        excess = row.get('female_excess_pct')
        try:
            excess_n = None if excess is None or excess == '' else int(excess)
        except (TypeError, ValueError):
            excess_n = None
        return {
            'age': int(age),
            'male_years': male,
            'female_years': female,
            'average_years': average,
            'female_excess_pct': excess_n,
        }
    return None


def adl3_rows_for_tables(tables: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Use a stored table when it has rows. An absent table uses the published default.

    A present-but-short table is kept as stored so a hole stays a hole.
    """
    stored = (tables or {}).get(TABLE_NAME)
    if isinstance(stored, list) and stored:
        return [dict(row) for row in stored if isinstance(row, dict)]
    return adl3_disabled_life_expectancy_rows()


def ensure_adl3_table(versions: Optional[Dict[str, Any]]) -> None:
    """Fill a missing expectancy table from the published default.

    Other keys on the version are left untouched. Nothing is written to disk.
    """
    if not isinstance(versions, dict):
        return
    for version in versions.values():
        if not isinstance(version, dict):
            continue
        stored = version.get(TABLE_NAME)
        if isinstance(stored, list) and stored:
            continue
        version[TABLE_NAME] = adl3_disabled_life_expectancy_rows()
