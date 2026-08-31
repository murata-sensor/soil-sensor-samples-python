"""SLT5008 (SDI-12) parsing tests."""

import pytest

from murata_soil_sensor import ProtocolError, SensorTimeoutError
from murata_soil_sensor import slt5008 as slt5008_module
from murata_soil_sensor.crc16 import encode_sdi12_crc
from murata_soil_sensor.slt5008 import Slt5008, read_concurrent, start_concurrent

from ._fake_transport import FakeTransport


@pytest.fixture
def slept(monkeypatch):
    """Record the concurrent-measurement waits instead of really sleeping."""
    calls: list[float] = []
    monkeypatch.setattr(slt5008_module.time, "sleep", calls.append)
    return calls


def _crc_line(payload: str) -> bytes:
    return f"{payload}{encode_sdi12_crc(payload)}\r\n".encode("ascii")


def _corrupt_crc(line: bytes) -> bytes:
    text = line.decode("ascii").removesuffix("\r\n")
    replacement = "@" if text[-1] != "@" else "A"
    return f"{text[:-1]}{replacement}\r\n".encode("ascii")


def test_parse_values_handles_sign():
    assert Slt5008.parse_values("0+100-4.5+6") == [100.0, -4.5, 6.0]


@pytest.mark.parametrize("payload", ["", "+1+2", "0garbage+1", "0+1x+2"])
def test_parse_values_rejects_malformed_payload(payload):
    with pytest.raises(ProtocolError, match="invalid SDI-12 data payload"):
        Slt5008.parse_values(payload)


def test_read_measurement_reads_d2_when_m_reports_eight_values():
    transport = FakeTransport(
        [
            b"00058\r\n0\r\n",                  # start response, then service request
            b"0+100+200+300+400+25.5+1500\r\n",  # aD0!
            b"0+42.0+2500\r\n",                  # aD1!
            b"0+11.1+22.2+3300\r\n",             # aD2!
        ]
    )
    m = Slt5008(address="0").read_measurement(transport)
    assert m.dds == 100
    assert m.adc_ec == 200
    assert m.adc_permittivity == 300
    assert m.adc_battery == 400
    assert m.temperature_c == pytest.approx(25.5)
    assert m.ec_bulk == pytest.approx(1500.0)
    assert m.vwc == pytest.approx(42.0)
    assert m.ec_pore == pytest.approx(2500.0)
    assert m.vwc_rock == pytest.approx(11.1)
    assert m.vwc_coco == pytest.approx(22.2)
    assert m.ec_pore_coco == pytest.approx(3300.0)
    assert transport.writes == [
        b"0M!\r\n",
        b"0D0!\r\n",
        b"0D1!\r\n",
        b"0D2!\r\n",
    ]


def test_mc_measurement_verifies_crc_on_d0_d1_and_d2():
    transport = FakeTransport(
        [
            b"00058\r\n0\r\n",  # start response has no CRC; service follows
            b"0+3085+2748+764+2632+29.6+0.03Fgd\r\n",
            b"0+14.2+2.46HcB\r\n",
            _crc_line("0+11.1+22.2+3.3"),
        ]
    )

    measurement = Slt5008(address="0", use_crc=True).read_measurement(transport)

    assert measurement.dds == 3085
    assert measurement.temperature_c == pytest.approx(29.6)
    assert measurement.ec_bulk == pytest.approx(0.03)
    assert measurement.vwc == pytest.approx(14.2)
    assert measurement.ec_pore == pytest.approx(2.46)
    assert measurement.vwc_rock == pytest.approx(11.1)
    assert measurement.vwc_coco == pytest.approx(22.2)
    assert measurement.ec_pore_coco == pytest.approx(3.3)
    assert transport.writes == [
        b"0MC!\r\n",
        b"0D0!\r\n",
        b"0D1!\r\n",
        b"0D2!\r\n",
    ]


def test_m_measurement_reads_data_after_ttt_when_service_request_is_not_seen(
    monkeypatch,
):
    times = iter([0.0, 5.0])
    monkeypatch.setattr(slt5008_module.time, "monotonic", lambda: next(times))
    transport = FakeTransport(
        [
            b"00058\r\n",
            b"0+100+200+300+400+25.5+1500\r\n",
            b"0+42.0+2500\r\n",
            b"0+11.1+22.2+3300\r\n",
        ]
    )

    measurement = Slt5008(address="0").read_measurement(transport)

    assert measurement.vwc == pytest.approx(42.0)


def test_service_request_wait_stops_at_declared_ttt(monkeypatch):
    times = iter([0.0, 4.9, 5.0])
    monkeypatch.setattr(slt5008_module.time, "monotonic", lambda: next(times))
    transport = FakeTransport([b""])

    Slt5008(address="0")._wait_ready(transport, 5.0)

    assert transport.read_until_delimiters == [b"\r\n"]
    assert transport.read_until_timeouts == [pytest.approx(0.1)]


@pytest.mark.parametrize("line", [b"0", b"No Response", b"1\r\n", b"0\xff\r\n"])
def test_incomplete_or_invalid_service_request_is_ignored_until_ttt(
    monkeypatch, line
):
    values = iter([0.0, 1.0, 5.0])
    calls = []

    def monotonic():
        calls.append(None)
        return next(values)

    monkeypatch.setattr(slt5008_module.time, "monotonic", monotonic)
    Slt5008(address="0")._wait_ready(FakeTransport([line]), 5.0)

    assert len(calls) == 3


def test_sdi12_short_write_is_a_timeout():
    transport = FakeTransport([b"0\r\n"], write_result=1)

    with pytest.raises(SensorTimeoutError, match="incomplete SDI-12"):
        Slt5008(address="0").acknowledge(transport)


def test_sdi12_partial_response_without_crlf_is_a_timeout():
    with pytest.raises(SensorTimeoutError, match="missing CR/LF"):
        Slt5008(address="0").acknowledge(FakeTransport([b"0"]))


def test_exact_converter_no_response_sentinel_is_absence_for_allow_empty_command():
    assert (
        Slt5008(address="0").acknowledge(FakeTransport([b"No Response\r\n"]))
        is False
    )


def test_exact_converter_no_response_sentinel_is_timeout_for_required_response():
    with pytest.raises(SensorTimeoutError, match="converter sentinel"):
        Slt5008(address="0").read_info(FakeTransport([b"No Response\r\n"]))


@pytest.mark.parametrize(
    "line",
    [
        b"No response\r\n",
        b"No Response \r\n",
        b"\x00No Response\x00\r\n",
        b"1\r\n",
    ],
)
def test_near_converter_sentinel_and_wrong_address_are_invalid_acknowledgements(line):
    with pytest.raises(ProtocolError, match="unexpected acknowledge-active"):
        Slt5008(address="0").acknowledge(FakeTransport([line]))


def test_sdi12_non_ascii_response_is_a_protocol_error():
    with pytest.raises(ProtocolError, match="non-ASCII"):
        Slt5008(address="0").acknowledge(FakeTransport([b"0\xff\r\n"]))


def test_sdi12_response_rejects_an_extra_line_ending_character():
    with pytest.raises(ProtocolError, match="embedded line ending"):
        Slt5008(address="0").acknowledge(FakeTransport([b"0\r\r\n"]))


def test_sdi12_boundary_nul_padding_is_tolerated():
    assert Slt5008(address="0").acknowledge(
        FakeTransport([b"\x000\x00\r\n"])
    )


@pytest.mark.parametrize("line", [b"\r\n", b"\x00\r\n", b"\x00\x00\r\n"])
def test_sdi12_nonempty_frame_without_a_payload_is_a_protocol_error(line):
    with pytest.raises(ProtocolError, match="empty framed"):
        Slt5008(address="0").acknowledge(FakeTransport([line]))


def test_crc_cannot_be_made_valid_by_deleting_an_embedded_nul():
    payload = "0+100+200+300+400+25.5+1.5"
    corrupted = payload.replace("+200", "\x00+200", 1)
    line = f"{corrupted}{encode_sdi12_crc(payload)}\r\n".encode("ascii")

    with pytest.raises(ProtocolError, match="embedded NUL"):
        Slt5008(address="0")._read_data_values(FakeTransport([line]), 0, True)


def test_crc_response_tolerates_converter_nul_boundary_padding():
    payload = "0+100+200+300+400+25.5+1.5"
    line = f"\x00{payload}{encode_sdi12_crc(payload)}\x00\r\n".encode("ascii")

    values = Slt5008(address="0")._read_data_values(
        FakeTransport([line]), 0, True
    )

    assert values == [100.0, 200.0, 300.0, 400.0, 25.5, 1.5]


def test_data_response_rejects_the_wrong_address():
    with pytest.raises(ProtocolError, match="unexpected address"):
        Slt5008(address="0")._read_data_values(
            FakeTransport([b"1+1+2+3+4+5+6\r\n"]), 0, False
        )


@pytest.mark.parametrize(
    "index,response",
    [
        (0, b"0+1+2+3+4+5\r\n"),
        (1, b"0+1+2+3\r\n"),
        (2, b"0\r\n"),
        (2, b"0+1+2\r\n"),
    ],
)
def test_data_response_rejects_unexpected_value_count(index, response):
    sensor = Slt5008(address="0")

    with pytest.raises(ProtocolError, match=f"D{index}"):
        sensor._read_data_values(FakeTransport([response]), index, False)


@pytest.mark.parametrize(
    ("field_index", "field_name", "value"),
    [
        (0, "DDS", "100.5"),
        (1, "ADC_EC", "200.5"),
        (2, "ADC_PERMITTIVITY", "300.5"),
        (3, "ADC_BATTERY", "400.5"),
        (0, "DDS", "-1"),
        (3, "ADC_BATTERY", "65536"),
    ],
)
def test_measurement_rejects_non_integral_or_out_of_range_raw_counts(
    field_index, field_name, value
):
    raw = ["100", "200", "300", "400"]
    raw[field_index] = value
    fields = [*raw, "25.5", "1.5"]
    body = "".join(part if part.startswith(("+", "-")) else f"+{part}" for part in fields)
    transport = FakeTransport(
        [
            f"0{body}\r\n".encode("ascii"),
            b"0+42+2.5\r\n",
            b"0+11.1+22.2+3.3\r\n",
        ]
    )

    with pytest.raises(ProtocolError, match=field_name):
        Slt5008(address="0").read_data(transport)


def test_measurement_accepts_unsigned_16_bit_raw_count_boundaries():
    transport = FakeTransport(
        [
            b"0+0+65535+0+65535+25.5+1.5\r\n",
            b"0+42+2.5\r\n",
            b"0+11.1+22.2+3.3\r\n",
        ]
    )

    measurement = Slt5008(address="0").read_data(transport)

    assert (
        measurement.dds,
        measurement.adc_ec,
        measurement.adc_permittivity,
        measurement.adc_battery,
    ) == (0, 65535, 0, 65535)


@pytest.mark.parametrize("corrupt_index", [0, 1, 2])
def test_mc_measurement_rejects_corrupt_crc_in_each_data_response(corrupt_index):
    data_lines = [
        _crc_line("0+3085+2748+764+2632+29.6+0.03"),
        _crc_line("0+14.2+2.46"),
        _crc_line("0+11.1+22.2+3.3"),
    ]
    data_lines[corrupt_index] = _corrupt_crc(data_lines[corrupt_index])
    transport = FakeTransport([b"00008\r\n", *data_lines])

    with pytest.raises(ProtocolError, match=rf"D{corrupt_index}"):
        Slt5008(address="0", use_crc=True).read_measurement(transport)


def test_read_info():
    # a(1) ll(2) cccccccc(8) mmmmmm(6) vvv(3) serial...
    ident = "013" + "MurataCo" + "LT5008" + "173" + "00012345"
    response = ident.encode("ascii") + b"\r\n"
    transport = FakeTransport([response], max_chunk_size=1)
    info = Slt5008(address="0").read_info(transport)
    assert info.sdi_version == "1.3"
    assert info.vendor == "MurataCo"
    assert info.model == "LT5008"
    assert info.firmware_version == "1.7.3"
    assert info.serial_number == 12345
    assert transport.read_sizes == [1] * len(response)


def test_slt5008_host_serial_format_is_fixed_to_8n1():
    config = Slt5008(baudrate=9600).serial_config
    assert (config.baudrate, config.bytesize, config.parity, config.stopbits) == (
        9600,
        8,
        "N",
        1,
    )
    with pytest.raises(TypeError):
        Slt5008(parity="E")


@pytest.mark.parametrize(
    "ident",
    [
        "013" + "OtherCo " + "LT5008" + "173" + "00012345",
        "013" + "MurataCo" + "OTHER " + "173" + "00012345",
        "013" + "MurataCo" + "LT5008" + "173" + "12X34",
        "013" + "MurataCo" + "LT5008" + "173",
        "013" + "MurataCo" + "LT5008" + "173" + "123456789",
    ],
)
def test_read_info_rejects_non_slt5008_or_invalid_serial(ident):
    with pytest.raises(ProtocolError, match="identification"):
        Slt5008(address="0").read_info(
            FakeTransport([ident.encode("ascii") + b"\r\n"])
        )


def test_read_info_without_response_is_a_timeout():
    with pytest.raises(SensorTimeoutError, match="no SDI-12 response"):
        Slt5008(address="0").read_info(FakeTransport([b""]))


def test_set_address_validation():
    with pytest.raises(ValueError):
        Slt5008(address="0").set_address(FakeTransport([]), 99)


def test_set_address_rejects_alpha():
    # SLT5008 accepts only digits 0-9 (A-Z is not supported).
    with pytest.raises(ValueError):
        Slt5008(address="0").set_address(FakeTransport([]), "A")


def test_address_rejects_non_ascii_digit():
    with pytest.raises(ValueError):
        Slt5008(address="０")


def test_set_address_accepts_echo_waits_one_second_and_verifies_new_address(slept):
    sensor = Slt5008(address="2")
    transport = FakeTransport([b"3\r\n", b"3\r\n"])

    sensor.set_address(transport, 3)

    assert sensor.address == "3"
    assert slept == [pytest.approx(1.0)]
    assert transport.writes == [b"2A3!\r\n", b"3!\r\n"]


def test_set_address_rejection_keeps_old_address_and_does_not_wait(slept):
    sensor = Slt5008(address="2")
    transport = FakeTransport([b"2\r\n"])

    with pytest.raises(ProtocolError, match="rejected"):
        sensor.set_address(transport, 3)

    assert sensor.address == "2"
    assert slept == []
    assert transport.writes == [b"2A3!\r\n"]


def test_set_address_without_command_response_is_a_timeout(slept):
    sensor = Slt5008(address="2")

    with pytest.raises(SensorTimeoutError, match="address-change response"):
        sensor.set_address(FakeTransport([b""]), 3)

    assert sensor.address == "2"
    assert slept == []


def test_set_address_times_out_if_new_address_does_not_answer(slept):
    sensor = Slt5008(address="2")
    transport = FakeTransport([b"3\r\n", b""])

    with pytest.raises(SensorTimeoutError, match="new address 3"):
        sensor.set_address(transport, 3)

    # The aAb! response confirmed the change even though the later probe timed out.
    assert sensor.address == "3"
    assert slept == [pytest.approx(1.0)]


def test_query_address_returns_the_reported_address():
    transport = FakeTransport([b"3\r\n"])
    assert Slt5008().query_address(transport) == "3"
    assert transport.writes[0] == b"?!\r\n"


def test_query_address_rejects_a_garbled_reply():
    # Two sensors answering ?! at once cannot be told apart.
    assert Slt5008().query_address(FakeTransport([b"03\r\n"])) is None


def test_query_address_rejects_a_non_digit_single_character():
    assert Slt5008().query_address(FakeTransport([b"X\r\n"])) is None


def test_acknowledge_matches_only_its_own_address():
    assert Slt5008(address="2").acknowledge(FakeTransport([b"2\r\n"])) is True
    assert Slt5008(address="2").acknowledge(FakeTransport([b""])) is False


def test_read_concurrent_returns_one_measurement_per_sensor(slept):
    transport = FakeTransport(
        [
            b"000011\r\n",  # 0 C! -> a ttt nn (nn is two digits for aC!)
            b"100011\r\n",  # 1 C!
            b"0+100+200+300+400+25.5+1500\r\n",  # 0 D0
            b"0+42.0+2500\r\n",                  # 0 D1
            b"0+11.1+22.2+3300\r\n",              # 0 D2
            b"1+110+210+310+410+26.0+1600\r\n",  # 1 D0
            b"1+43.0+2600\r\n",                  # 1 D1
            b"1+12.1+23.2+3400\r\n",              # 1 D2
        ]
    )
    sensor0, sensor1 = Slt5008(address="0"), Slt5008(address="1")
    measurements = read_concurrent([sensor0, sensor1], transport)
    assert len(measurements) == 2
    assert measurements[0].temperature_c == pytest.approx(25.5)
    assert measurements[1].temperature_c == pytest.approx(26.0)


def test_read_concurrent_waits_out_the_declared_conversion_time(slept):
    # aC! sends no service request, so the reader must wait ttt out on its own;
    # addressing a sensor earlier would abort its measurement.
    transport = FakeTransport(
        [
            b"000211\r\n",  # 0 C! -> ttt = 002
            b"100411\r\n",  # 1 C! -> ttt = 004
            b"0+100+200+300+400+25.5+1500\r\n",
            b"0+42.0+2500\r\n",
            b"0+11.1+22.2+3300\r\n",
            b"1+110+210+310+410+26.0+1600\r\n",
            b"1+43.0+2600\r\n",
            b"1+12.1+23.2+3400\r\n",
        ]
    )
    read_concurrent([Slt5008(address="0"), Slt5008(address="1")], transport)
    assert len(slept) == 1
    assert slept[0] == pytest.approx(4.0, abs=0.5)


def test_read_concurrent_starts_all_sensors_before_reading_data(slept):
    transport = FakeTransport(
        [
            b"000011\r\n",
            b"100011\r\n",
            b"0+100+200+300+400+25.5+1500\r\n",
            b"0+42.0+2500\r\n",
            b"0+11.1+22.2+3300\r\n",
            b"1+110+210+310+410+26.0+1600\r\n",
            b"1+43.0+2600\r\n",
            b"1+12.1+23.2+3400\r\n",
        ]
    )
    read_concurrent([Slt5008(address="0"), Slt5008(address="1")], transport)
    writes = [w.decode() for w in transport.writes]
    start_commands = [i for i, w in enumerate(writes) if w.endswith("C!\r\n")]
    data_commands = [i for i, w in enumerate(writes) if "D0!" in w]
    assert len(start_commands) == 2
    assert max(start_commands) < min(data_commands)


def test_concurrent_measurement_validates_sensor_list():
    transport = FakeTransport()
    with pytest.raises(ValueError, match="at least two"):
        start_concurrent([Slt5008(address="0")], transport)
    with pytest.raises(ValueError, match="unique"):
        start_concurrent(
            [Slt5008(address="0"), Slt5008(address="0")], transport
        )
    with pytest.raises(TypeError, match="only SLT5008"):
        start_concurrent([Slt5008(address="0"), object()], transport)

    assert transport.writes == []


def test_cc_measurement_verifies_crc_for_multiple_sensors(slept):
    transport = FakeTransport(
        [
            b"000011\r\n",  # 0CC! -> ttt=000, nn=11
            b"100011\r\n",  # 1CC! -> ttt=000, nn=11
            _crc_line("0+100+200+300+400+25.5+1.5"),
            _crc_line("0+42+2.5"),
            _crc_line("0+11.1+22.2+3.3"),
            _crc_line("1+110+210+310+410+26+1.6"),
            _crc_line("1+43+2.6"),
            _crc_line("1+12.1+23.2+3.4"),
        ]
    )
    sensors = [
        Slt5008(address="0", use_crc=True),
        Slt5008(address="1", use_crc=True),
    ]

    measurements = read_concurrent(sensors, transport)

    assert measurements[0].ec_pore_coco == pytest.approx(3.3)
    assert measurements[1].ec_pore_coco == pytest.approx(3.4)
    assert transport.writes[:2] == [b"0CC!\r\n", b"1CC!\r\n"]
    assert b"0D2!\r\n" in transport.writes
    assert b"1D2!\r\n" in transport.writes


@pytest.mark.parametrize(
    ("command", "response"),
    [
        ("M", b"10058\r\n"),       # wrong response address
        ("MC", b"00A58\r\n"),      # non-numeric ttt
        ("M", b"0005\r\n"),        # missing value count
        ("CC", b"00058\r\n"),      # C/CC requires a two-digit count
        ("M", b"00050\r\n"),       # zero values are invalid for SLT5008
        ("M", b"00057\r\n"),       # current M/MC layout must report 8
        ("C", b"000508\r\n"),      # current C/CC layout must report 11
    ],
)
def test_start_measurement_rejects_malformed_response(command, response):
    sensor = Slt5008(address="0")

    with pytest.raises(ProtocolError, match=f"unexpected {command} response"):
        sensor._start_measurement(FakeTransport([response]), command)


def test_start_measurement_rejects_declared_time_beyond_limit():
    sensor = Slt5008(address="0", measurement_timeout=4.0)

    with pytest.raises(SensorTimeoutError, match="exceeding"):
        sensor._start_measurement(FakeTransport([b"00058\r\n"]), "M")
