# Сохранить как lib/ssd1322.py
import framebuf
from micropython import const

_SET_COL_ADDR = const(0x15)
_SET_ROW_ADDR = const(0x75)
_WRITE_RAM = const(0x5C)
_READ_RAM = const(0x5D)
_SET_REMAP = const(0xA0)
_SET_START_LINE = const(0xA1)
_SET_OFFSET = const(0xA2)
_ENTIRE_ON_NORMAL = const(0xA4)
_ENTIRE_ON_ALL = const(0xA5)
_ENTIRE_OFF = const(0xA6)
_INVERSE_OFF = const(0xA6)
_INVERSE_ON = const(0xA7)
_SET_MUX_RATIO = const(0xCA)
_SET_COMMAND_LOCK = const(0xFD)
_SET_CONTRAST_CURRENT = const(0xC1)
_SET_MASTER_CURRENT = const(0xC7)
_SET_PRECHARGE_VOLTAGE = const(0xBB)
_SET_VCOMH_VOLTAGE = const(0xBE)
_EXIT_SLEEP = const(0xAF)
_SET_SLEEP = const(0xAE)
_SET_PHASE_LENGTH = const(0xB1)
_SET_CLOCK_DIV = const(0xB3)
_SET_PRECHARGE_PERIOD = const(0xB6)
_SET_SECOND_PRECHARGE_PERIOD = const(0xB6)

class SSD1322(framebuf.FrameBuffer):
    def __init__(self, width, height, spi, res, cs, dc):
        self.width = width
        self.height = height
        self.spi = spi
        self.res = res
        self.cs = cs
        self.dc = dc
        self.buffer = bytearray(self.width * self.height // 2)
        # GS4_HMSB means 4-bit grayscale (16 shades of gray)
        super().__init__(self.buffer, self.width, self.height, framebuf.GS4_HMSB)
        self.res.init(self.res.OUT, value=1)
        self.cs.init(self.cs.OUT, value=1)
        self.dc.init(self.dc.OUT, value=0)
        self.init_display()

    def write_cmd(self, cmd):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytearray([cmd]))
        self.cs(1)

    def write_data(self, data):
        self.cs(0)
        self.dc(1)
        self.spi.write(bytearray([data]))
        self.cs(1)

    def init_display(self):
        self.res(1)
        import time
        time.sleep_ms(1)
        self.res(0)
        time.sleep_ms(10)
        self.res(1)
        
        self.write_cmd(_SET_COMMAND_LOCK)
        self.write_data(0x12)  # Unlock
        self.write_cmd(_SET_SLEEP) # Display OFF
        
        self.write_cmd(_SET_CLOCK_DIV)
        self.write_data(0x91)
        self.write_cmd(_SET_MUX_RATIO)
        self.write_data(0x3F) # 1/64 duty
        self.write_cmd(_SET_OFFSET)
        self.write_data(0x00)
        self.write_cmd(_SET_START_LINE)
        self.write_data(0x00)
        
        self.write_cmd(_SET_REMAP)
        # Настройка сканирования (может потребоваться подбор под вашу плату)
        self.write_data(0x14) # Horizontal address increment, Disable Column Address Re-map, Enable Nibble Re-map
        self.write_data(0x11) # Dual COM line mode
        
        self.write_cmd(_SET_CONTRAST_CURRENT) # Яркость
        self.write_data(0x7F) # Max 0xFF
        
        self.write_cmd(_SET_MASTER_CURRENT)
        self.write_data(0x0F) # Max
        
        self.write_cmd(_EXIT_SLEEP) # Display ON

    def show(self):
        self.write_cmd(_SET_COL_ADDR)
        self.write_data(0x1C) # Start column (смещение часто нужно 0x1C для центровки)
        self.write_data(0x5B) # End column
        self.write_cmd(_SET_ROW_ADDR)
        self.write_data(0x00)
        self.write_data(0x3F)
        self.write_cmd(_WRITE_RAM)
        self.cs(0)
        self.dc(1)
        self.spi.write(self.buffer)
        self.cs(1)