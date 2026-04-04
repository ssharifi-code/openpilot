"""
LC500 DHP Signal Validation — validates DBC against real rlog CAN data.
Toolchain: pycapnp 2.2.2 + cantools 41.3.0 (pure Python, no Cython needed)
"""
import os, sys, json, shutil, tempfile
from collections import Counter, defaultdict

import capnp
import cantools

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

DBC_PATH = r'D:\Envs\sunnypilot\opendbc\dbc\lexus_lc_dhp_generated.dbc'
RLOG_PATH = r'D:\Envs\qlogs\rlog_seg1.bin'
CEREAL_DIR = r'D:\Envs\openpilot\openpilot\cereal'
REAL_CAR_CAPNP = r'D:\Envs\openpilot\openpilot\opendbc_repo\opendbc\car\car.capnp'
OUTPUT_JSON = r'D:\Envs\sunnypilot\lc500_signal_validation_report.json'

# Critical signals that openpilot/sunnypilot carstate.py MUST parse
CRITICAL_SIGNALS = {
    'WHEEL_SPEEDS': {
        'signals': ['WHEEL_SPEED_FR', 'WHEEL_SPEED_FL', 'WHEEL_SPEED_RR', 'WHEEL_SPEED_RL'],
        'range': (0, 300),  # km/h
        'min_hz': 30,
    },
    'BRAKE_MODULE': {
        'signals': ['BRAKE_PRESSURE', 'BRAKE_POSITION', 'BRAKE_PRESSED'],
        'range': None,
        'min_hz': 20,
    },
    'STEER_TORQUE_SENSOR': {
        'signals': ['STEER_TORQUE_DRIVER', 'STEER_ANGLE', 'STEER_TORQUE_EPS'],
        'range': None,
        'min_hz': 50,
    },
    'EPS_STATUS': {
        'signals': ['LKA_STATE'],
        'range': None,
        'min_hz': 10,
    },
    'GAS_PEDAL': {
        'signals': ['GAS_RELEASED', 'GAS_PEDAL'],
        'range': None,
        'min_hz': 20,
    },
    'STEERING_LKA': {
        'signals': ['STEER_REQUEST', 'STEER_TORQUE_CMD'],
        'range': None,
        'min_hz': 50,
    },
    'PCM_CRUISE': {
        'signals': ['CRUISE_ACTIVE', 'GAS_RELEASED', 'CRUISE_STATE'],
        'range': None,
        'min_hz': 20,
    },
    'PCM_CRUISE_2': {
        'signals': ['MAIN_ON', 'SET_SPEED', 'LOW_SPEED_LOCKOUT'],
        'range': None,
        'min_hz': 20,
    },
    'PCM_CRUISE_SM': {
        'signals': ['MAIN_ON', 'CRUISE_CONTROL_STATE', 'UI_SET_SPEED'],
        'range': None,
        'min_hz': 0.5,  # State machine — low frequency OK
    },
}

# ═══════════════════════════════════════════════════════════════════
# STEP 1: Load cereal schema
# ═══════════════════════════════════════════════════════════════════

def load_log_schema():
    tmpdir = tempfile.mkdtemp(prefix='cereal_')
    for f in ['log.capnp', 'legacy.capnp', 'custom.capnp']:
        shutil.copy2(os.path.join(CEREAL_DIR, f), tmpdir)
    shutil.copy2(REAL_CAR_CAPNP, tmpdir)
    include_dst = os.path.join(tmpdir, 'include')
    shutil.copytree(os.path.join(CEREAL_DIR, 'include'), include_dst)
    return capnp.load(os.path.join(tmpdir, 'log.capnp'), imports=[tmpdir, include_dst])

# ═══════════════════════════════════════════════════════════════════
# STEP 2: Extract CAN frames from rlog
# ═══════════════════════════════════════════════════════════════════

def extract_can_frames(rlog_path, log_capnp):
    frames = []  # list of (address, dat_bytes, src)
    event_count = 0
    can_event_count = 0
    with open(rlog_path, 'rb') as f:
        for event in log_capnp.Event.read_multiple(f):
            event_count += 1
            if event.which() == 'can':
                can_event_count += 1
                for msg in event.can:
                    frames.append((msg.address, bytes(msg.dat), msg.src))
    return frames, event_count, can_event_count

# ═══════════════════════════════════════════════════════════════════
# STEP 3: Decode all CAN frames through DBC
# ═══════════════════════════════════════════════════════════════════

def decode_frames(frames, db):
    # Build address → message lookup
    addr_to_msg = {m.frame_id: m for m in db.messages}

    results = defaultdict(list)  # msg_name → list of decoded dicts
    decode_errors = defaultdict(int)
    unmatched = Counter()

    for address, dat, src in frames:
        if address in addr_to_msg:
            msg = addr_to_msg[address]
            try:
                decoded = msg.decode(dat, decode_choices=False)
                results[msg.name].append(decoded)
            except Exception as e:
                decode_errors[msg.name] += 1
        else:
            unmatched[address] += 1

    return dict(results), dict(decode_errors), dict(unmatched)

# ═══════════════════════════════════════════════════════════════════
# STEP 4: Validate signals
# ═══════════════════════════════════════════════════════════════════

def validate(results, decode_errors, unmatched, total_frames, segment_seconds=60.0):
    report = {
        'summary': {},
        'critical_signals': {},
        'dbc_coverage': {},
        'unmatched_addresses': {},
        'decode_errors': decode_errors,
    }

    # DBC coverage: how many of our 54 DBC messages appear in traffic?
    total_dbc_msgs = 54
    matched_dbc = len(results)
    report['dbc_coverage'] = {
        'dbc_messages_defined': total_dbc_msgs,
        'dbc_messages_seen_in_traffic': matched_dbc,
        'coverage_pct': round(100 * matched_dbc / total_dbc_msgs, 1),
        'messages_seen': sorted(results.keys()),
        'messages_not_seen': sorted(set(m for m in ['WHEEL_SPEEDS','BRAKE_MODULE','STEER_TORQUE_SENSOR',
            'EPS_STATUS','GAS_PEDAL','STEERING_LKA','PCM_CRUISE_SM','PCM_CRUISE','PCM_CRUISE_2',
            'STEER_ANGLE_SENSOR','KINEMATICS','SPEED','ENGINE_RPM','ACC_CONTROL','GEAR_PACKET',
            'BODY_CONTROL_STATE','BLINKERS_STATE','ESP_CONTROL','BRAKE_2',
            'DSU_SPEED','DSU_CRUISE','LKAS_HUD','PCS_HUD','LEAD_INFO','PRE_COLLISION',
            'BRAKE','CLUTCH','GAS_PEDAL_HYBRID','GEAR_PACKET_HYBRID',
            'STEERING_IPAS','AUTOPARK_STATUS','LIGHT_STALK','TIME','AUTO_HIGH_BEAM',
            'SOLAR_SENSOR','REVERSE_CAMERA_STATE','BODY_CONTROL_STATE_2','UI_SETTING',
            'RSA1','RSA2','RSA3','VIN_PART_1','VIN_PART_2','VIN_PART_3',
            'ADAS_TOGGLE_STATE','CERTIFICATION_ECU','DOOR_LOCKS','PRE_COLLISION_2',
            'PCM_CRUISE_ALT','VSC1S07','VSC1S08','VSC1S29','ENG2F41','ENG2F42']) - set(results.keys())),
    }

    # Unmatched addresses (CAN IDs not in DBC)
    report['unmatched_addresses'] = {
        'count': len(unmatched),
        'top_20': [{'address': f'0x{a:03X}', 'count': c} for a, c in
                   sorted(unmatched.items(), key=lambda x: -x[1])[:20]],
    }

    # Critical signal validation
    all_pass = True
    for msg_name, spec in CRITICAL_SIGNALS.items():
        entry = {'present': msg_name in results, 'msg_count': 0, 'signals': {}}
        if msg_name in results:
            decoded_list = results[msg_name]
            entry['msg_count'] = len(decoded_list)
            entry['approx_hz'] = round(len(decoded_list) / segment_seconds, 1)
            entry['hz_ok'] = entry['approx_hz'] >= spec['min_hz']

            for sig_name in spec['signals']:
                values = [d.get(sig_name) for d in decoded_list if sig_name in d]
                if not values:
                    entry['signals'][sig_name] = {'present': False, 'error': 'signal not in any decoded frame'}
                    all_pass = False
                    continue
                numeric = [v for v in values if isinstance(v, (int, float))]
                if numeric:
                    sig_report = {
                        'present': True,
                        'count': len(values),
                        'min': round(min(numeric), 4),
                        'max': round(max(numeric), 4),
                        'mean': round(sum(numeric) / len(numeric), 4),
                        'all_zero': all(v == 0 for v in numeric),
                        'unique_values': min(len(set(numeric)), 50),
                    }
                    if spec.get('range'):
                        lo, hi = spec['range']
                        sig_report['in_range'] = lo <= sig_report['min'] and sig_report['max'] <= hi
                        if not sig_report['in_range']:
                            all_pass = False
                else:
                    # Enumerated / string values
                    sig_report = {
                        'present': True,
                        'count': len(values),
                        'unique_values': list(set(str(v) for v in values))[:20],
                        'all_zero': False,
                    }
                entry['signals'][sig_name] = sig_report
            if not entry['hz_ok']:
                all_pass = False
        else:
            entry['error'] = f'Message {msg_name} NOT FOUND in CAN traffic'
            all_pass = False
        report['critical_signals'][msg_name] = entry

    report['summary'] = {
        'total_can_frames': total_frames,
        'dbc_coverage_pct': report['dbc_coverage']['coverage_pct'],
        'critical_signals_all_pass': all_pass,
        'decode_error_count': sum(decode_errors.values()),
        'unmatched_address_count': len(unmatched),
    }

    return report

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 70)
    print("LC500 DHP Signal Validation")
    print("=" * 70)

    print("\n[1/4] Loading cereal schema...")
    log_capnp = load_log_schema()
    print("  OK")

    print(f"\n[2/4] Extracting CAN frames from {RLOG_PATH}...")
    frames, event_count, can_event_count = extract_can_frames(RLOG_PATH, log_capnp)
    print(f"  Events: {event_count}, CAN events: {can_event_count}, CAN frames: {len(frames)}")

    print(f"\n[3/4] Decoding {len(frames)} frames through DBC ({DBC_PATH})...")
    db = cantools.database.load_file(DBC_PATH, strict=False)
    results, decode_errors, unmatched = decode_frames(frames, db)
    print(f"  Matched messages: {len(results)}, Decode errors: {sum(decode_errors.values())}, Unmatched IDs: {len(unmatched)}")

    print("\n[4/4] Validating signals...")
    report = validate(results, decode_errors, unmatched, len(frames))

    # Save report
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved to {OUTPUT_JSON}")

    # Print summary
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    s = report['summary']
    print(f"  Total CAN frames: {s['total_can_frames']}")
    print(f"  DBC coverage: {s['dbc_coverage_pct']}%")
    print(f"  Decode errors: {s['decode_error_count']}")
    print(f"  Unmatched CAN IDs: {s['unmatched_address_count']}")
    print(f"  Critical signals ALL PASS: {s['critical_signals_all_pass']}")

    print("\nCritical signal details:")
    for msg_name, entry in report['critical_signals'].items():
        status = "+" if entry['present'] and entry.get('hz_ok', False) else "X"
        hz = entry.get('approx_hz', 0)
        count = entry.get('msg_count', 0)
        print(f"  [{status}] {msg_name}: {count} msgs ({hz} Hz)")
        for sig_name, sig in entry.get('signals', {}).items():
            if sig.get('present'):
                if 'min' in sig:
                    z = " [ALL ZERO]" if sig.get('all_zero') else ""
                    print(f"      {sig_name}: min={sig['min']}, max={sig['max']}, mean={sig['mean']}, unique={sig['unique_values']}{z}")
                else:
                    print(f"      {sig_name}: values={sig.get('unique_values', '?')}")
            else:
                print(f"      {sig_name}: MISSING -- {sig.get('error', '?')}")

    if not s['critical_signals_all_pass']:
        print("\nWARNING: SOME CRITICAL SIGNALS FAILED -- review details above")
        sys.exit(1)
    else:
        print("\nALL CRITICAL SIGNALS VALIDATED")
        sys.exit(0)
