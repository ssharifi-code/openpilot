"""
LC500 CI Test Suite
Run: python -m pytest opendbc/car/toyota/tests/test_lc500.py -v
Windows: TestLC500Config skips (ABI mismatch) — TestLC500DBC runs fine via cantools
"""
import os
import re
import pytest
import cantools

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
DBC_PATH  = os.path.join(REPO_ROOT, "opendbc", "dbc", "lexus_lc_dhp_generated.dbc")

# Guard: skip Python-native opendbc imports on Windows Python 3.13 (ABI mismatch)
CAN_IMPORT = True
try:
    from opendbc.car.toyota.values import CAR, STATIC_DSU_MSGS, EPS_SCALE, UNSUPPORTED_DSU_CAR
    from opendbc.car.toyota.fingerprints import FW_VERSIONS
    from opendbc.car import Ecu
except (ImportError, OSError):
    CAN_IMPORT = False


# ── Config tests (require opendbc import — skip on Windows) ──────────────────

@pytest.mark.skipif(not CAN_IMPORT, reason="opendbc import unavailable on this platform")
class TestLC500Config:
    def test_platform_exists(self):
        assert hasattr(CAR, "LEXUS_LC")

    def test_steer_ratio_plausible(self):
        sr = CAR.LEXUS_LC.config.specs.steerRatio
        assert 11.0 <= sr <= 16.0, f"steerRatio {sr} out of expected range"

    def test_wheelbase(self):
        wb = CAR.LEXUS_LC.config.specs.wheelbase
        assert abs(wb - 2.87) < 0.01, f"wheelbase {wb} != 2.87m"

    def test_mass_kg_plausible(self):
        m = CAR.LEXUS_LC.config.specs.mass
        # 4280 lb = 1941 kg; allow +/- 100 kg for trim variants
        assert 1800 <= m <= 2200, f"mass {m} kg out of range (expected ~1941)"

    def test_fw_versions_has_7_ecus(self):
        assert CAR.LEXUS_LC in FW_VERSIONS
        assert len(FW_VERSIONS[CAR.LEXUS_LC]) == 7

    def test_dsu_ecu_address(self):
        ecus = FW_VERSIONS[CAR.LEXUS_LC]
        dsu = [(e, a, s) for (e, a, s) in ecus if e == Ecu.dsu]
        assert len(dsu) == 1
        assert dsu[0] == (Ecu.dsu, 0x791, None)

    def test_eps_ecu_address(self):
        ecus = FW_VERSIONS[CAR.LEXUS_LC]
        eps = [(e, a, s) for (e, a, s) in ecus if e == Ecu.eps]
        assert len(eps) >= 1
        assert any(a == 0x7a1 for _, a, _ in eps)

    def test_eps_scale_73(self):
        assert EPS_SCALE.get(CAR.LEXUS_LC, 73) == 73

    def test_static_dsu_at_least_8(self):
        lc_entries = [t for t in STATIC_DSU_MSGS if CAR.LEXUS_LC in t[1]]
        assert len(lc_entries) >= 8, (
            f"LEXUS_LC in only {len(lc_entries)} STATIC_DSU_MSGS tuples (expected >= 8)"
        )

    def test_not_in_radar_dsu_msgs(self):
        radar_addrs = {0x2E6, 0x2E7, 0x33E}
        bad = [t for t in STATIC_DSU_MSGS if CAR.LEXUS_LC in t[1] and t[0] in radar_addrs]
        assert not bad, f"LEXUS_LC incorrectly appears in radar DSU tuples: {bad}"

    def test_not_in_unsupported_dsu(self):
        assert CAR.LEXUS_LC not in UNSUPPORTED_DSU_CAR

    def test_rlog_fw_bytes_engine(self):
        fw = b"\x0131106000\x00\x00\x00\x00\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.engine, 0x7e0, None), [])
        assert fw in variants, "rlog engine@7e0 FW bytes missing from FW_VERSIONS"

    def test_rlog_fw_bytes_abs(self):
        fw = b"F152611031\x00\x00\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.abs, 0x7b0, None), [])
        assert fw in variants, "rlog abs@7b0 FW bytes missing from FW_VERSIONS"

    def test_rlog_fw_bytes_dsu(self):
        fw = b"881511101200\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.dsu, 0x791, None), [])
        assert fw in variants, "rlog dsu@791 FW bytes missing from FW_VERSIONS"

    def test_rlog_fw_bytes_eps(self):
        fw = b"8965B11010\x00\x00\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.eps, 0x7a1, None), [])
        assert fw in variants, "rlog eps@7a1 FW bytes missing from FW_VERSIONS"

    def test_rlog_fw_bytes_radar(self):
        fw = b"8821F4702300\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.fwdRadar, 0x750, 0xf), [])
        assert fw in variants, "rlog fwdRadar@750/f FW bytes missing from FW_VERSIONS"

    def test_rlog_fw_bytes_camera(self):
        fw = b"8646F1101300\x00\x00\x00\x00"
        variants = FW_VERSIONS[CAR.LEXUS_LC].get((Ecu.fwdCamera, 0x750, 0x6d), [])
        assert fw in variants, "rlog fwdCamera@750/6d FW bytes missing from FW_VERSIONS"


# ── DBC tests (cantools only — run on Windows and Linux) ─────────────────────

class TestLC500DBC:
    def setup_method(self):
        assert os.path.exists(DBC_PATH), f"DBC not found at {DBC_PATH}"
        self.db = cantools.database.load_file(DBC_PATH, strict=False)

    def test_dbc_file_size(self):
        size = os.path.getsize(DBC_PATH)
        assert size > 20000, f"DBC too small: {size} bytes (expected ~30625)"

    def test_dbc_message_count(self):
        assert len(self.db.messages) > 50, (
            f"Only {len(self.db.messages)} messages in DBC — likely truncated"
        )

    def test_steering_lka(self):
        msg = self.db.get_message_by_name("STEERING_LKA")
        assert msg.frame_id == 0x2E4
        assert msg.length == 5

    def test_steering_lka_signals(self):
        msg = self.db.get_message_by_name("STEERING_LKA")
        names = {s.name for s in msg.signals}
        # Must have at minimum steer torque command and enable bit
        assert any("STEER" in n.upper() or "LKA" in n.upper() for n in names), (
            f"STEERING_LKA has no steer-related signals: {names}"
        )

    def test_pcm_cruise_2(self):
        msg = self.db.get_message_by_name("PCM_CRUISE_2")
        assert msg.frame_id == 0x1D3

    def test_acc_control(self):
        msg = self.db.get_message_by_name("ACC_CONTROL")
        assert msg.frame_id == 0x343

    def test_steer_torque_sensor(self):
        msg = self.db.get_message_by_name("STEER_TORQUE_SENSOR")
        assert msg.frame_id == 0x260

    def test_wheel_speeds_message(self):
        msg = self.db.get_message_by_name("WHEEL_SPEEDS")
        assert msg is not None

    def test_brake_message(self):
        # Should have BRAKE or BRAKE_MODULE
        names = {m.name for m in self.db.messages}
        assert any("BRAKE" in n for n in names), f"No BRAKE message in DBC: {names}"

    def test_no_ars_vgrs_definitions(self):
        with open(DBC_PATH, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        for pattern in ["ARS_STATUS", "VGRS_STATUS", "REAR_STEER", "VARIABLE_GEAR"]:
            matches = re.findall(pattern, content, re.IGNORECASE)
            assert not matches, (
                f"Unexpected '{pattern}' found in DBC ({len(matches)} occurrences). "
                f"ARS/VGRS CAN IDs must be identified from on-vehicle candump before adding."
            )

    def test_dbc_no_duplicate_message_ids(self):
        ids = [m.frame_id for m in self.db.messages]
        duplicates = {i for i in ids if ids.count(i) > 1}
        assert not duplicates, f"Duplicate message IDs in DBC: {[hex(d) for d in duplicates]}"

    def test_dbc_all_signals_have_names(self):
        unnamed = []
        for msg in self.db.messages:
            for sig in msg.signals:
                if not sig.name or sig.name.startswith("_"):
                    unnamed.append((msg.name, sig.name))
        assert not unnamed, f"Unnamed signals in DBC: {unnamed[:10]}"


# ── Safety model tests (cantools-based) ──────────────────────────────────────

class TestLC500Safety:
    def test_steering_lka_dlc_5(self):
        db = cantools.database.load_file(DBC_PATH, strict=False)
        msg = db.get_message_by_name("STEERING_LKA")
        assert msg.length == 5, (
            f"STEERING_LKA DLC={msg.length}, panda toyota safety expects DLC=5"
        )

    def test_acc_control_dlc_8(self):
        db = cantools.database.load_file(DBC_PATH, strict=False)
        msg = db.get_message_by_name("ACC_CONTROL")
        assert msg.length == 8, (
            f"ACC_CONTROL DLC={msg.length}, expected 8 for Toyota panda safety"
        )

    def test_no_messages_above_0x800(self):
        db = cantools.database.load_file(DBC_PATH, strict=False)
        extended = [m for m in db.messages if m.frame_id > 0x7FF]
        # Toyota OEM CAN uses standard 11-bit IDs only on pt bus
        # Extended IDs on pt bus would indicate DBC misconfiguration
        assert not extended, (
            f"Extended-ID messages found (unexpected for Toyota pt bus): "
            f"{[(hex(m.frame_id), m.name) for m in extended]}"
        )
