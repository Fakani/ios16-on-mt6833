import os
K = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel/mtk/loader')
SPI = os.path.join(K, 'mtkspi.h')

s = open(SPI).read()
if '0x11018000ULL' in s:
    print('already patched'); raise SystemExit

# 1. the controller: SPI2 (0x11012000) -> SPI4 (0x11018000)
old = "#define SPI2_BASE            0x11012000ULL"
new = "#define SPI2_BASE            0x11018000ULL   /* SPI4: the touch controller (DT spi4@11018000) */"
assert old in s
s = s.replace(old, new, 1)

# 2. the pads: MT6768's SPI2 pins 25..28 -> MT6833's SPI4 pins 12,13,97,98,99,100
old_fn = """static void spi_pins_to_spi2(void)
{
	uint32_t mode = rd32(GPIO_BASE + GPIO_MODE3);

	for (int pin = SPI2_PIN_CS; pin <= SPI2_PIN_MI; pin++) {
		uint32_t shift = (uint32_t)(pin % 8) * 4;

		mode = (mode & ~(0xfu << shift)) | ((uint32_t)SPI2_PIN_FUNC << shift);
	}
	wr32(GPIO_BASE + GPIO_MODE3, mode);
	__asm__ volatile("dsb sy");
}"""
new_fn = """/*
 * MT6833 SPI4's pads.  Android leaves GPIO_MODE1 (0x310) = 0x00220007 and
 * GPIO_MODE12 (0x3C0) = 0x11122221: pins 12 and 13 in function 2, and pins
 * 97..100 in function 2.  The MT6768 values this used to write (pins 25..28,
 * GPIO_MODE3) belong to a different SoC's SPI2 and touch nothing here.
 */
static void spi_pins_to_spi2(void)
{
	static const uint8_t pins[] = { 12, 13, 97, 98, 99, 100 };

	for (unsigned i = 0; i < sizeof(pins) / sizeof(pins[0]); i++) {
		uint32_t pin = pins[i];
		uint32_t reg = GPIO_MODE0 + (pin / 8) * 0x10;
		uint32_t shift = (pin % 8) * 4;
		uint32_t v = rd32(GPIO_BASE + reg);

		v = (v & ~(0xfu << shift)) | (2u << shift);
		wr32(GPIO_BASE + reg, v);
	}
	__asm__ volatile("dsb sy");
}"""
assert old_fn in s, 'pin function body not found'
s = s.replace(old_fn, new_fn, 1)

# GPIO_MODE0 may not be defined; add it next to GPIO_MODE3
if 'GPIO_MODE0' not in s:
    s = s.replace("#define GPIO_MODE3           0x330",
                  "#define GPIO_MODE0           0x300\n#define GPIO_MODE3           0x330", 1)
open(SPI, 'w').write(s)
print('mtkspi.h: base 0x11012000 -> 0x11018000 (SPI4); pads 25..28 -> 12,13,97..100')
