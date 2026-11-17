"""Hardware-free regression checks for final GUI protocol utilities."""
from pathlib import Path
import tempfile
import types
import sys

# The transmitter import normally requires pyserial; protocol tests do not.
try:
    import serial  # noqa
except ImportError:
    module = types.ModuleType('serial')
    module.SerialException = type('SerialException', (Exception,), {})
    tools = types.ModuleType('serial.tools')
    ports = types.ModuleType('serial.tools.list_ports')
    ports.comports = lambda: []
    module.tools = tools
    tools.list_ports = ports
    sys.modules.update({'serial':module,'serial.tools':tools,'serial.tools.list_ports':ports})

from Morse_IR_Transmitter_Studio_FINAL import phase8_prepare_packets, phase8_verify_packets
from Morse_IR_Receiver_Studio_FINAL import selftest as receiver_selftest

with tempfile.TemporaryDirectory() as tmp:
    fp = Path(tmp) / 'message.txt'
    fp.write_text('HELLO WORLD THIS IS OUR MORSE IR FILE TRANSFER PROJECT', encoding='ascii')
    for address in ('01','02'):
        expected, packets = phase8_prepare_packets(fp, address)
        assert len(packets) == 2
        assert phase8_verify_packets(packets, address) == expected
        try:
            phase8_verify_packets(packets[:1], address)
        except ValueError:
            pass
        else:
            raise AssertionError('Missing packet was not rejected')
        damaged = list(packets)
        damaged[-1] = damaged[-1][:-3] + '999'
        try:
            phase8_verify_packets(damaged, address)
        except ValueError:
            pass
        else:
            raise AssertionError('Corrupted checksum was not rejected')
    print('TX TESTS PASS: both addresses, file reconstruction, missing packet and checksum corruption')

receiver_selftest()
print('ALL FINAL-STUDIO OFFLINE REGRESSIONS PASS')
