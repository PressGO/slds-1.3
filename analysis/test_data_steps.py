"""test_data_steps.py - tests every step in data_steps.py on small made-up data with known answers.

    .venv/bin/python analysis/test_data_steps.py -v

Each expected value below was worked out by hand from the rules in data_settings.py, not by running the code.
AI disclosure: drafted with Claude (Anthropic) on 14 Nov 2026; log in AI_USE.md.
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import polars as pl  # noqa: E402

import data_settings as S  # noqa: E402
import data_steps as D     # noqa: E402

T = datetime


def at(h: int, m: int, day: date = date(2026, 10, 19)) -> datetime:
    return T(day.year, day.month, day.day, h, m)


def deg_east(metres: float) -> float:
    return metres / (D.M_PER_DEG * D.COS_LAT)


class TimeTests(unittest.TestCase):
    def test_parse_sgt(self):
        s = pl.DataFrame({"x": ["2026-11-10T00:01:50+0800", "2026-10-13T00:00:00+08:00", "2026-11-10 00:00:00",
                                "2026-11-10 07:05", "garbage", None]})
        got = s.select(D.parse_sgt(pl.col("x")))["x"].to_list()
        self.assertEqual(got, [T(2026, 11, 10, 0, 1, 50), T(2026, 10, 13), T(2026, 11, 10), T(2026, 11, 10, 7, 5),
                               None, None])

    def test_slot15(self):
        s = pl.DataFrame({"t": [at(0, 0), at(6, 0), at(6, 14), at(6, 15), at(21, 59), at(23, 45)]})
        self.assertEqual(s.select(D.slot15(pl.col("t")))["t"].to_list(), [0, 24, 24, 25, 87, 95])

    def test_file_time(self):
        self.assertEqual(D.file_time(Path("sb_20261110_000150.csv.gz")), T(2026, 11, 10, 0, 1, 50))
        self.assertEqual(D.file_time(Path("sbraw_20261110_0000.jsonl.gz")), T(2026, 11, 10))
        self.assertEqual(D.file_time(Path("incidents_20261114_182431.jsonl.gz")), T(2026, 11, 14, 18, 24, 31))
        self.assertIsNone(D.file_time(Path("notes.csv")))


class DayTests(unittest.TestCase):
    def test_day_table(self):
        # the proposal's splits: train to Fri 6 Nov, validate Sat 7 - Fri 13 Nov, test Sat 14 - Fri 20 Nov
        d = D.day_table(date(2026, 11, 6), date(2026, 11, 23), {date(2026, 11, 8), date(2026, 11, 9)})
        got = {r["date"]: (r["daytype"], r["split"], r["in_population"]) for r in d.iter_rows(named=True)}
        self.assertEqual(got[date(2026, 11, 6)], ("weekday", "train", True))             # Friday
        self.assertEqual(got[date(2026, 11, 7)], ("saturday", "validate", False))
        self.assertEqual(got[date(2026, 11, 8)], ("sunday_or_holiday", "validate", False))  # Sunday, Deepavali
        self.assertEqual(got[date(2026, 11, 9)], ("sunday_or_holiday", "validate", False))  # Monday, holiday
        self.assertEqual(got[date(2026, 11, 10)], ("weekday", "validate", True))
        self.assertEqual(got[date(2026, 11, 13)], ("weekday", "validate", True))         # Friday
        self.assertEqual(got[date(2026, 11, 14)], ("saturday", "test", False))
        self.assertEqual(got[date(2026, 11, 16)], ("weekday", "test", True))
        self.assertEqual(got[date(2026, 11, 20)], ("weekday", "test", True))             # Friday, last test day
        self.assertEqual(got[date(2026, 11, 21)], ("saturday", None, False))
        self.assertEqual(got[date(2026, 11, 23)], ("weekday", None, True))
        self.assertEqual(d.filter(pl.col("date") == date(2026, 11, 9))["weekday"].item(), 1)
        self.assertTrue(d.filter(pl.col("date") == date(2026, 11, 9))["is_holiday"].item())


class SpeedBandTests(unittest.TestCase):
    def test_clean_keeps_earliest_and_counts(self):
        raw = pl.DataFrame({
            "retrieved": [T(2026, 10, 19, 10, 1), T(2026, 10, 19, 10, 2), T(2026, 10, 19, 10, 1),
                          T(2026, 10, 19, 10, 0, 30), T(2026, 10, 19, 10, 6), T(2026, 10, 19, 10, 6)],
            "t": [at(10, 0), at(10, 0), at(10, 0), at(10, 0), None, at(10, 5)],
            "LinkID": ["L1", "L1", "L2", "L2", "L3", "L3"],
            "SpeedBand": [5, 5, 3, 4, 5, 9],
            "file_no": [0, 1, 0, 2, 3, 3], "row_no": [0, 0, 1, 0, 0, 1]},
            schema_overrides={"file_no": pl.Int32, "row_no": pl.UInt32})
        panel, st = D.clean_speedbands(raw)
        self.assertEqual(panel.select("t", "LinkID", "band").rows(),
                         [(at(10, 0), "L1", 5), (at(10, 0), "L2", 4), (at(10, 5), "L3", None)])
        self.assertEqual(panel.filter(pl.col("LinkID") == "L2")["retrieved"].item(), T(2026, 10, 19, 10, 0, 30))
        self.assertEqual((st["no_update_time"], st["band_outside_1_8"], st["conflicts"],
                          st["link_updates_fetched_twice_or_more"], st["rows_kept"]), (1, 1, 1, 2, 3))

    def test_read_speedband_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sb_20261019_100150.csv.gz"
            with gzip.open(p, "wt") as f:
                f.write("retrieved_at,last_updated,LinkID,SpeedBand\n"
                        "2026-10-19T10:01:50+0800,2026-10-19 10:00:00,7,6\n"
                        "2026-10-19T10:01:50+0800,2026-10-19 09:55:00,8,2\n"
                        "2026-10-19T10:01:50+0800,2026-10-19 10:00:00,9,8\n")
            df = D.read_speedband_file(p, ["7", "8"], 4)
        self.assertEqual(df.select("retrieved", "t", "LinkID", "SpeedBand", "file_no", "row_no").rows(),
                         [(T(2026, 10, 19, 10, 1, 50), at(10, 0), "7", 6, 4, 0),
                          (T(2026, 10, 19, 10, 1, 50), at(9, 55), "8", 2, 4, 1)])


class RegistryTests(unittest.TestCase):
    def test_read_and_build(self):
        def page(p, recs, when):
            body = {"odata.metadata": "x", "lastUpdatedTime": "2026-10-19 10:00:00", "value": recs}
            return json.dumps({"endpoint": "TrafficSpeedBands", "retrieved_at": when, "page": p,
                               "body": json.dumps(body)}) + "\n"
        rec = lambda i, cat, lon: {"LinkID": i, "RoadName": "R" + i, "RoadCategory": cat, "SpeedBand": 8,
                                   "MinimumSpeed": "70", "MaximumSpeed": "999", "StartLon": str(lon),
                                   "StartLat": "1.3", "EndLon": str(lon + 0.001), "EndLat": "1.3"}
        with tempfile.TemporaryDirectory() as tmp:
            f0, f1 = Path(tmp) / "a.jsonl.gz", Path(tmp) / "b.jsonl.gz"
            with gzip.open(f0, "wt") as f:
                f.write(page(1, [rec("1", "1", 103.80)], "2026-10-19T10:01:00+0800"))
            with gzip.open(f1, "wt") as f:
                f.write(page(1, [rec("1", "1", 103.90)], "2026-10-19T11:01:00+0800"))
                f.write(page(2, [rec("2", "4", 103.70)], "2026-10-19T11:01:00+0800"))
            s0, s1 = D.read_registry_file(f0, 0), D.read_registry_file(f1, 1)
        reg = D.build_registry(pl.concat([D.registry_versions(s0), D.registry_versions(s1)]), 2)
        # the same link and version seen in two batches counts both files
        same = D.build_registry(pl.concat([D.registry_versions(s0), D.registry_versions(s0.with_columns(
            pl.lit(5, pl.Int32).alias("file_no"), (pl.col("retrieved") + timedelta(hours=1)).alias("retrieved")))]), 2)
        self.assertEqual(same.select("n_snapshots", "n_attribute_versions", "last_seen").row(0),
                         (2, 1, T(2026, 10, 19, 11, 1)))
        r1 = reg.filter(pl.col("LinkID") == "1").row(0, named=True)
        r2 = reg.filter(pl.col("LinkID") == "2").row(0, named=True)
        self.assertEqual((r1["StartLon"], r1["n_snapshots"], r1["n_attribute_versions"], r1["presence_snapshots"]),
                         (103.90, 2, 2, 1.0))
        self.assertEqual((r2["RoadCategory"], r2["n_snapshots"], r2["presence_snapshots"], r2["n_categories"]),
                         (4, 1, 0.5, 1))
        self.assertEqual(r1["first_seen"], T(2026, 10, 19, 10, 1))


class GeometryTests(unittest.TestCase):
    def test_neighbours_within_5m(self):
        e = 103.801
        links = pl.DataFrame({"LinkID": ["A", "B", "C", "D"],
                              "StartLon": [103.800, e, e + deg_east(4), e + deg_east(6)],
                              "StartLat": [1.3] * 4,
                              "EndLon": [e, 103.802, 103.803, 103.804], "EndLat": [1.3] * 4})
        p = D.neighbour_pairs(links)
        self.assertEqual(p.select("LinkID", "downstream").rows(), [("A", "B"), ("A", "C")])
        self.assertAlmostEqual(p["gap_m"][1], 4.0, places=2)

    def test_connectors(self):
        reg = pl.DataFrame({"LinkID": ["X1", "X2", "R1", "R2", "R3"], "RoadName": ["XW", "XW", "SLIP", "SLIP", "FAR"],
                            "RoadCategory": [1, 1, 4, 4, 2],
                            "StartLon": [103.800, 103.801, 103.799, 103.801, 103.799],
                            "StartLat": [1.3, 1.3, 1.3, 1.3, 1.3],
                            "EndLon": [103.801, 103.802, 103.800, 103.802, 103.800 - deg_east(7)],
                            "EndLat": [1.3, 1.3, 1.3, 1.301, 1.3]})
        c = D.connector_pairs(reg, ["X1", "X2"])
        self.assertEqual(c.select("LinkID", "joins", "kind").rows(), [("R1", "X1", "into"), ("R2", "X1", "out_of")])

    def test_nearest_station(self):
        links = pl.DataFrame({"LinkID": ["L"], "StartLon": [103.80], "StartLat": [1.30], "EndLon": [103.80], "EndLat": [1.30]})
        st = pl.DataFrame({"station_id": ["S2", "S1"], "lat": [1.30, 1.31], "lon": [103.85, 103.80]})
        n = D.nearest_station(links, st)
        self.assertEqual(n["station_id"].item(), "S1")
        self.assertAlmostEqual(n["station_km"].item(), 1.112, places=3)


class PopulationNormTests(unittest.TestCase):
    def test_presence(self):
        ts = [at(6, 5 * k) for k in range(10)]
        panel = pl.DataFrame({"t": ts + ts[:9] + [at(5, 55), T(2026, 10, 18, 9, 0)],
                              "LinkID": ["A"] * 10 + ["B"] * 9 + ["B", "B"],
                              "band": [8] * 21}, schema_overrides={"band": pl.Int8})
        pres, n = D.presence_week1(panel, ["A", "B", "C"])
        self.assertEqual(n, 10)
        self.assertEqual(pres.rows(), [("A", 1.0), ("B", 0.9), ("C", 0.0)])

    def test_normal_level_train_days_and_daytypes(self):
        days = D.day_table(date(2026, 10, 19), date(2026, 11, 10), set())
        panel = pl.DataFrame({"t": [at(10, 0), at(10, 14, date(2026, 10, 20)), at(10, 0, date(2026, 11, 10)),
                                    at(10, 0, date(2026, 10, 24)), at(10, 15)],
                              "LinkID": ["L"] * 5, "band": [8, 5, 1, 3, 2]}, schema_overrides={"band": pl.Int8})
        n = D.normal_level(panel, days)
        got = {(r["daytype"], r["slot15"]): (r["norm_band"], r["n_obs"], r["n_days"]) for r in n.iter_rows(named=True)}
        self.assertEqual(got[("weekday", 40)], (6.5, 2, 2))    # median of 8 and 5; 10 Nov (validate) not used
        self.assertEqual(got[("saturday", 40)], (3.0, 1, 1))
        self.assertEqual(got[("weekday", 41)], (2.0, 1, 1))     # 10:15 is the next slot
        self.assertEqual(len(got), 3)


class GridLabelLagTests(unittest.TestCase):
    """One link, norm 8 everywhere, 10:00-11:30 on a training Monday. Bands by minute after 10:00
    (None = update missing): the hand-worked deficits, labels and look-backs are below."""
    bands = {0: 8, 5: 8, 10: 6, 15: 5, 20: None, 25: 5, 30: None, 35: None, 40: 6, 45: 7, 50: 8}

    def grid(self):
        days = D.day_table(date(2026, 10, 19), date(2026, 10, 19), set())
        norm = pl.DataFrame({"LinkID": ["L1"] * 96, "daytype": ["weekday"] * 96,
                             "slot15": list(range(96)), "norm_band": [8.0] * 96},
                            schema_overrides={"slot15": pl.Int16})
        rows = [(at(10, 0) + timedelta(minutes=m), "L1", self.bands.get(m, 8))
                for m in range(0, 95, 5) if self.bands.get(m, 8) is not None]
        panel = pl.DataFrame(rows, schema={"t": pl.Datetime("us"), "LinkID": pl.Utf8, "band": pl.Int8}, orient="row")
        g = D.deficit_grid(panel, norm, days, ["L1"], at(10, 0), at(11, 30))
        return D.add_lags(D.add_labels(g), prefix="f_")

    def val(self, g, minute, col):
        return g.filter(pl.col("t") == at(10, 0) + timedelta(minutes=minute))[col].item()

    def test_deficit_and_carry(self):
        g = self.grid()
        self.assertEqual(g.height, 19)
        self.assertEqual([self.val(g, m, "deficit") for m in (0, 10, 15, 20, 25, 30, 35, 40, 45)],
                         [0, 2, 3, None, 3, None, None, 2, 1])
        self.assertEqual([self.val(g, m, "dfill") for m in (20, 30, 35)], [3, 3, None])   # 5 min at most
        self.assertEqual([self.val(g, m, "filled") for m in (15, 20, 30, 35)], [False, True, True, False])

    def test_strict_label(self):
        g = self.grid()
        self.assertEqual([self.val(g, m, "U") for m in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)],
                         [None, False, False, True, None, None, None, None, None, False, False, False])
        self.assertEqual([self.val(g, m, "y") for m in (0, 5, 10, 25, 30, 35, 40)],
                         [True, None, None, None, False, False, False])
        self.assertEqual([self.val(g, m, "y") for m in (80, 85, 90)], [None, None, None])   # past the grid
        self.assertEqual([self.val(g, m, "y_h5") for m in (0, 5, 10, 40)], [False, False, True, False])
        self.assertEqual([self.val(g, m, "y_h10") for m in (0, 5)], [False, True])
        self.assertEqual([self.val(g, m, "y_h30") for m in (0, 15, 20)], [None, False, False])

    def test_lags(self):
        g = self.grid()
        self.assertEqual([self.val(g, 40, f"f_d{k}") for k in S.LAGS], [2, None, 3, 3, 3, 3, 2])
        self.assertEqual(self.val(g, 40, "f_n_filled"), 2)
        self.assertEqual([self.val(g, 50, f"f_d{k}") for k in S.LAGS], [0, 1, 2, None, 3, 3, 3])
        self.assertEqual(self.val(g, 50, "f_n_filled"), 2)
        self.assertEqual([self.val(g, 0, f"f_d{k}") for k in S.LAGS], [0, None, None, None, None, None, None])


class InputTests(unittest.TestCase):
    def lagged(self, values: dict) -> pl.DataFrame:
        t = at(10, 0)
        rows = [{"nbr": k, "t": t, **{c: v[i] for i, c in enumerate(D.DCOLS)}} for k, v in values.items()]
        return pl.DataFrame(rows, schema={"nbr": pl.Utf8, "t": pl.Datetime("us"), **{c: pl.Float32 for c in D.DCOLS}})

    def test_neighbours(self):
        rows = pl.DataFrame({"LinkID": ["A", "B", "C", "D"], "t": [at(10, 0)] * 4})
        pairs = pl.DataFrame({"LinkID": ["A", "A"], "downstream": ["B", "C"], "gap_m": [0.0, 0.0]})
        lag = self.lagged({"A": [5, 5, 5, 5, 5, 5, 5], "B": [1, None, 1, 1, 1, 1, 1], "C": [3, None, 0, 0, 0, 0, None]})
        out = D.neighbour_inputs(rows, pairs, lag).sort("LinkID")
        a = out.row(0, named=True)
        self.assertEqual((a["f_dn_d0"], a["f_dn_d5"], a["f_dn_d10"], a["f_dn_d30"], a["f_dn_none"]), (3, None, 1, 1, 0))
        self.assertEqual((a["f_up_none"], a["f_up_d0"], a["f_up_d30"]), (1, 0.0, 0.0))
        b = out.row(1, named=True)
        self.assertEqual((b["f_up_d0"], b["f_up_none"], b["f_dn_none"], b["f_dn_d0"]), (5, 0, 1, 0.0))
        d = out.row(3, named=True)
        self.assertEqual((d["f_up_none"], d["f_dn_none"], d["f_up_d5"], d["f_dn_d5"]), (1, 1, 0.0, 0.0))

    def test_connectors(self):
        rows = pl.DataFrame({"LinkID": ["A", "B"], "t": [at(10, 0)] * 2})
        conn = pl.DataFrame({"LinkID": ["X", "Z", "Y"], "joins": ["A", "A", "A"], "kind": ["into", "into", "out_of"]})
        lag = self.lagged({"X": [1, 2, 3, 4, 5, 6, 7], "Z": [7, 0, 0, 0, 0, 0, 0]})
        out = D.connector_inputs(rows, conn, lag).sort("LinkID")
        a, b = out.row(0, named=True), out.row(1, named=True)
        self.assertEqual([a[f"f_conn_in_{c}"] for c in D.DCOLS], [7, 2, 3, 4, 5, 6, 7])
        self.assertEqual((a["f_conn_in_none"], a["f_conn_in_missing"]), (0, 0))
        self.assertEqual((a["f_conn_out_none"], a["f_conn_out_missing"], a["f_conn_out_d0"]), (0, 1, 0.0))
        self.assertEqual((b["f_conn_in_none"], b["f_conn_in_missing"], b["f_conn_out_none"], b["f_conn_in_d0"]), (1, 0, 1, 0.0))

    def test_rain(self):
        rain = pl.DataFrame({"t": [at(10, 0), at(10, 5), at(10, 15), at(10, 20)], "station_id": ["S"] * 4,
                             "rain_mm": [1.0, 2.0, 4.0, 8.0]})
        r = D.rain_inputs(rain, ["S"], at(9, 0), at(10, 30))
        v = lambda h, m, c: r.filter(pl.col("t") == at(h, m))[c].item()
        self.assertEqual((v(10, 20, "f_rain15"), v(10, 20, "f_rain30")), (6.0, 7.0))    # never the reading at t
        self.assertEqual((v(10, 30, "f_rain15"), v(10, 30, "f_rain30")), (12.0, 15.0))
        self.assertEqual((v(10, 5, "f_rain15"), v(10, 5, "f_rain15_missing")), (1.0, 0))
        self.assertEqual((v(9, 30, "f_rain15"), v(9, 30, "f_rain15_missing"), v(9, 30, "f_rain30_missing")), (0.0, 1, 1))

    def test_rain_exactly_zero_after_rain(self):
        # 0.2 and 0.6 mm are not exact in binary: a running float total would leave about 1e-16 behind
        ts = [at(10, 0) + timedelta(minutes=5 * k) for k in range(30)]
        mm = [0.0, 0.2, 0.6, 0.2, 0.6, 0.2] + [0.0] * 24
        rain = pl.DataFrame({"t": ts, "station_id": ["S"] * 30, "rain_mm": mm})
        r = D.rain_inputs(rain, ["S"], at(10, 0), ts[-1])
        late = r.filter(pl.col("t") >= at(11, 0))            # every window after 11:00 holds zeros only
        self.assertTrue((late["f_rain15"] == 0.0).all() and (late["f_rain30"] == 0.0).all())
        self.assertEqual(r.filter(pl.col("t") == at(10, 30))["f_rain30"].item(), 1.8)   # 0.2+0.6+0.2+0.6+0.2
        self.assertEqual(r.filter(pl.col("t") == at(10, 20))["f_rain15"].item(), 1.0)   # 0.2+0.6+0.2
        self.assertTrue((r["f_rain15"] >= 0).all())
        self.assertEqual(r.filter(pl.col("t") == at(10, 15))["f_rain15"].item(), 0.8)   # 0.2+0.6: printed as 0.8

    def test_calendar(self):
        rows = pl.DataFrame({"t": [at(6, 0), at(21, 55)], "weekday": [1, 7], "is_holiday": [True, False]},
                            schema_overrides={"weekday": pl.Int8})
        out = D.calendar_inputs(rows)
        self.assertEqual(out.select("f_slot15", *S.WEEKDAY_COLUMNS, "f_holiday").rows(),
                         [(24, 1, 0, 0, 0, 0, 0, 0, 1), (87, 0, 0, 0, 0, 0, 0, 1, 0)])

    def test_column_lists(self):
        core, extra = D.core_input_columns(), D.connector_input_columns()
        self.assertEqual(len(core), len(set(core)))
        self.assertFalse(set(core) & set(extra))
        self.assertTrue(all(c.startswith("f_") for c in core + extra))
        self.assertNotIn("f_prev_missing", core)
        self.assertEqual((len(core), len(extra)), (38, 18))
        main = D.model_input_columns()                     # the main files: no f_sat, f_sun, f_holiday
        self.assertEqual(main, [c for c in core if c not in ("f_sat", "f_sun", "f_holiday")])
        self.assertEqual(len(main), 35)
        self.assertIn("f_fri", main)

    def test_heldout_roads(self):
        roads = ["TAMPINES EXPRESSWAY", "AYER RAJAH EXPRESSWAY", "BUKIT TIMAH EXPRESSWAY", "CENTRAL EXPRESSWAY",
                 "EAST COAST PARKWAY", "KALLANG PAYA LEBAR EXPRESSWAY", "KRANJI EXPRESSWAY", "SELETAR EXPRESSWAY",
                 "MARINA COASTAL EXPRESSWAY", "PAN ISLAND EXPRESSWAY", "ALJUNIED WEST FLYOVER", "KALLANG BAHRU FLYOVER"]
        # the draw of data versions 1-2: random.Random(20261113).sample(the 10 sorted expressways, 2)
        self.assertEqual(D.heldout_roads(roads), ["AYER RAJAH EXPRESSWAY", "CENTRAL EXPRESSWAY"])
        self.assertEqual(D.heldout_roads(list(reversed(roads)) + roads), D.heldout_roads(roads))   # order, repeats
        self.assertEqual(tuple(D.heldout_roads(roads)), S.EXPECTED_HELDOUT)


class IncidentTests(unittest.TestCase):
    def test_episodes(self):
        t = [T(2026, 10, 19, 8, 0) + timedelta(minutes=2 * k) for k in range(6)]
        k = ("Accident", "(19/10)08:01 Accident on PIE", 1.3, 103.8)
        m = ("Vehicle breakdown", "(19/10)08:07 Vehicle breakdown on CTE", 1.35, 103.85)
        rows = [(0, t[0], None, None, None, None)]
        for s in (1, 2, 4):
            rows.append((s, t[s], *k))
        rows.append((3, t[3], None, None, None, None))
        for s in (4, 5):
            rows.append((s, t[s], *m))
        snaps = pl.DataFrame(rows, schema={"snap_no": pl.Int32, "retrieved": pl.Datetime("us"), "Type": pl.Utf8,
                                           "Message": pl.Utf8, "Latitude": pl.Float64, "Longitude": pl.Float64},
                             orient="row")
        ep = D.incident_episodes(snaps)
        self.assertEqual(ep.select("type", "first_seen", "last_seen_before").rows(),
                         [("Accident", t[1], t[3]), ("Accident", t[4], t[5]), ("Vehicle breakdown", t[4], None)])
        self.assertEqual(ep["reported"].to_list(), [T(2026, 10, 19, 8, 1), T(2026, 10, 19, 8, 1), T(2026, 10, 19, 8, 7)])

    def test_read_incident_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "incidents_20261019_080000.jsonl.gz"
            body = {"odata.metadata": "x", "value": [{"Type": "Accident", "Latitude": 1.3, "Longitude": 103.8,
                                                      "Message": "(19/10)08:01 Accident on PIE"}]}
            with gzip.open(p, "wt") as f:
                f.write(json.dumps({"endpoint": "TrafficIncidents", "retrieved_at": "2026-10-19T08:00:00+0800",
                                    "page": 1, "body": json.dumps(body)}) + "\n")
                f.write(json.dumps({"endpoint": "TrafficIncidents", "retrieved_at": "2026-10-19T08:00:00+0800",
                                    "page": 2, "body": json.dumps({"value": []})}) + "\n")
            df = D.read_incident_file(p, 3)
        self.assertEqual(df.filter(pl.col("Type").is_not_null()).select("snap_no", "Type").rows(), [(3, "Accident")])

    def test_empty_incident_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "incidents_20261019_080200.jsonl.gz"
            with gzip.open(p, "wt") as f:
                f.write("")
            df = D.read_incident_file(p, 7)
        self.assertEqual(df.select("snap_no", "retrieved", "Type").rows(), [(7, T(2026, 10, 19, 8, 2), None)])


if __name__ == "__main__":
    unittest.main()
