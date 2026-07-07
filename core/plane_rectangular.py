"""
Japan Plane Rectangular Coordinate System (平面直角座標系) -> lat/lon conversion.

This is a genuinely different coordinate system from lat/lon, not another
notation for it: X/Y are meters measured from one of 19 zone-specific
origins, and (unlike the usual convention) X is the north-south axis while
Y is east-west.

Port of the widely-used Kawase (2011) / GSI series-expansion algorithm on
the GRS80 ellipsoid (JGD2000/JGD2011), matching Navi-Toll's
lib/planeRectangular.js so the two tools agree on results.
"""

import math
from typing import Optional

_GRS80_A = 6378137.0
_GRS80_F = 298.257222101
_M0 = 0.9999

# [origin latitude, origin longitude] in degrees, per 平成14年国土交通省告示第9号
_ZONE_ORIGINS = {
    1: (33.0, 129 + 30 / 60), 2: (33.0, 131.0), 3: (36.0, 132 + 10 / 60),
    4: (33.0, 133 + 30 / 60), 5: (36.0, 134 + 20 / 60), 6: (36.0, 136.0),
    7: (36.0, 137 + 10 / 60), 8: (36.0, 138 + 30 / 60), 9: (36.0, 139 + 50 / 60),
    10: (40.0, 140 + 50 / 60), 11: (44.0, 140 + 15 / 60), 12: (44.0, 142 + 15 / 60),
    13: (44.0, 144 + 15 / 60), 14: (26.0, 142.0), 15: (26.0, 127 + 30 / 60),
    16: (26.0, 124.0), 17: (26.0, 131.0), 18: (20.0, 136.0), 19: (26.0, 154.0),
}


def plane_rectangular_to_latlon(x: float, y: float, zone: int) -> Optional[tuple[float, float]]:
    """Convert Plane Rectangular CS (X, Y in meters) for the given zone (1-19) to (lat, lon) in decimal degrees."""
    origin = _ZONE_ORIGINS.get(zone)
    if origin is None:
        return None
    lat0 = math.radians(origin[0])
    lon0 = math.radians(origin[1])

    n = 1 / (2 * _GRS80_F - 1)
    n2, n3, n4, n5, n6 = n ** 2, n ** 3, n ** 4, n ** 5, n ** 6

    a = [
        1 + (1 / 4) * n2 + (1 / 64) * n4,
        -(3 / 2) * (n - (1 / 8) * n3 - (1 / 64) * n5),
        (15 / 16) * (n2 - (1 / 4) * n4),
        -(35 / 48) * (n3 - (5 / 16) * n5),
        (315 / 512) * n4,
        -(693 / 1280) * n5,
    ]

    beta = [
        0.0,
        0.5 * n - (2 / 3) * n2 + (37 / 96) * n3 - (1 / 360) * n4 - (81 / 512) * n5,
        (1 / 48) * n2 + (1 / 15) * n3 - (437 / 1440) * n4 + (46 / 105) * n5,
        (17 / 480) * n3 - (37 / 840) * n4 - (209 / 4480) * n5,
        (4397 / 161280) * n4 - (11 / 504) * n5,
        (4583 / 161280) * n5,
    ]

    delta = [
        0.0,
        2 * n - (2 / 3) * n2 - 2 * n3 + (116 / 45) * n4 + (26 / 45) * n5 - (2854 / 675) * n6,
        (7 / 3) * n2 - (8 / 5) * n3 - (227 / 45) * n4 + (2704 / 315) * n5 + (2323 / 945) * n6,
        (56 / 15) * n3 - (136 / 35) * n4 - (1262 / 105) * n5 + (73815 / 2835) * n6,
        (4279 / 630) * n4 - (332 / 35) * n5 - (399572 / 14175) * n6,
        (4174 / 315) * n5 - (144838 / 6237) * n6,
        (601676 / 22275) * n6,
    ]

    a_bar = (_M0 * _GRS80_A) / (1 + n) * a[0]
    s_bar = a[0] * lat0
    for j in range(1, 6):
        s_bar += a[j] * math.sin(2 * j * lat0)
    s_bar *= (_M0 * _GRS80_A) / (1 + n)

    xi = (x + s_bar) / a_bar
    eta = y / a_bar

    xi_prime, eta_prime = xi, eta
    for j in range(1, 6):
        xi_prime -= beta[j] * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        eta_prime -= beta[j] * math.cos(2 * j * xi) * math.sinh(2 * j * eta)

    chi = math.asin(math.sin(xi_prime) / math.cosh(eta_prime))
    lat = chi
    for j in range(1, 7):
        lat += delta[j] * math.sin(2 * j * chi)
    lon = lon0 + math.atan(math.sinh(eta_prime) / math.cos(xi_prime))

    return math.degrees(lat), math.degrees(lon)
