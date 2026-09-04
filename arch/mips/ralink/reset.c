// SPDX-License-Identifier: GPL-2.0-only
/*
 *
 * Copyright (C) 2008-2009 Gabor Juhos <juhosg@openwrt.org>
 * Copyright (C) 2008 Imre Kaloz <kaloz@openwrt.org>
 * Copyright (C) 2013 John Crispin <john@phrozen.org>
 */

#include <linux/pm.h>
#include <linux/io.h>
#include <linux/of.h>
#include <linux/delay.h>

#include <asm/reboot.h>

#include <asm/mach-ralink/ralink_regs.h>

/* Reset Control */
#define SYSC_REG_RESET_CTRL	0x034

#define RSTCTL_RESET_PCI	BIT(26)
#define RSTCTL_RESET_SYSTEM	BIT(0)
#define RSTCTL_RESET_FE		BIT(21)
#define RSTCTL_RESET_ESW		BIT(23)
#define RSTCTL_RESET_EPHY	BIT(24)

static void ralink_restart(char *command)
{
	if (IS_ENABLED(CONFIG_PCI)) {
		rt_sysc_m32(0, RSTCTL_RESET_PCI, SYSC_REG_RESET_CTRL);
		mdelay(50);
	}

	/* A system reset alone can leave the MT7620 Ethernet blocks active. */
	if (ralink_soc == MT762X_SOC_MT7620A ||
	    ralink_soc == MT762X_SOC_MT7620N) {
		rt_sysc_m32(0, RSTCTL_RESET_FE | RSTCTL_RESET_ESW |
			    RSTCTL_RESET_EPHY, SYSC_REG_RESET_CTRL);
		/* Restart runs in atomic context. */
		udelay(100);
	}

	local_irq_disable();
	rt_sysc_w32(RSTCTL_RESET_SYSTEM, SYSC_REG_RESET_CTRL);
	unreachable();
}

static int __init mips_reboot_setup(void)
{
	_machine_restart = ralink_restart;

	return 0;
}

arch_initcall(mips_reboot_setup);
