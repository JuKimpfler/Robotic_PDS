# Communication Protocol Specification

## SPI Frame Format (Teensy -> RPi)
Offset   Size    Type          Field
0        2       uint16        magic (0xABCD)
2        2       uint16        sequence
4        4       uint32        timestamp_us
8        2       uint16        channel_count
10       2       uint16        flags (Bit 0: frame_rate_ack)
12       N×4     float32[N]    values
12+N×4   2       uint16        crc16

## UDP Sub-Packet Format (RPi -> PC)
Offset   Size    Type         Field
0        2       uint16       magic (0xCDAB)
2        2       uint16       frame_seq
4        2       uint16       channel_count
6        1       uint8        sub_id (0=first, 1=second)
7        1       uint8        sub_total (2)
8        2       uint16       offset
10       2       uint16       payload_count
12       M×4     float32[M]   values
12+M×4   2       uint16       crc16
