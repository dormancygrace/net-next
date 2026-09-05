// SPDX-License-Identifier: GPL-2.0-only
/*
 * MediaTek MT7620 integrated Fast Ethernet PHYs.
 * Tuning values from the Ralink initialization sequence used by OpenWrt
 * gsw_mt7620.c (John Crispin, Felix Fietkau and Michael Lee).
 */
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/phy.h>
#include <linux/regmap.h>

#include "phylib.h"

#define MT7620_PHY_ID		0x03a29400
#define MT7620_PHY_COUNT	5
#define MT7620_PHY_PAGE		0x1f
#define MT7620_SYSC_REV		0x0c
#define MT7620_SYSC_REV_BGA	BIT(16)

struct mt7620_ephy_shared {
	bool bga;
	bool initialized;
};

static int mt7620_ephy_read_page(struct phy_device *phydev)
{
	return __phy_read(phydev, MT7620_PHY_PAGE);
}

static int mt7620_ephy_write_page(struct phy_device *phydev, int page)
{
	return __phy_write(phydev, MT7620_PHY_PAGE, page);
}

static int mt7620_ephy_init_shared(struct phy_device *phydev)
{
	static const struct {
		u16 page;
		u8 reg;
		u16 bga;
		u16 qfn;
	} tuning[] = {
		{ 0x4000, 17, 0x7444, 0x7444 },
		{ 0x4000, 19, 0x0114, 0x0117 },
		{ 0x4000, 22, 0x10cf, 0x10cf },
		{ 0x4000, 25, 0x6212, 0x6212 },
		{ 0x4000, 26, 0x0777, 0x0777 },
		{ 0x4000, 29, 0x4000, 0x4000 },
		{ 0x4000, 28, 0xc077, 0xc077 },
		{ 0x4000, 24, 0x0000, 0x0000 },
		{ 0x3000, 17, 0x4838, 0x4838 },
		{ 0x2000, 21, 0x0515, 0x0517 },
		{ 0x2000, 22, 0x0053, 0x0fd2 },
		{ 0x2000, 23, 0x00bf, 0x00bf },
		{ 0x2000, 24, 0x0aaf, 0x0aab },
		{ 0x2000, 25, 0x0fad, 0x00ae },
		{ 0x2000, 26, 0x0fc1, 0x0fff },
		{ 0x1000, 17, 0xe7f8, 0xe7f8 },
	};
	struct mt7620_ephy_shared *shared = phy_package_get_priv(phydev);
	int i, oldpage, ret, restore;

	/* Global analog registers are accessed through PHY address 1. Keep
	 * the bus locked across page selection, tuning and page restoration.
	 */
	phy_lock_mdio_bus(phydev);
	oldpage = __phy_package_read(phydev, 1, MT7620_PHY_PAGE);
	if (oldpage < 0) {
		ret = oldpage;
		goto unlock;
	}

	for (i = 0; i < ARRAY_SIZE(tuning); i++) {
		ret = __phy_package_write(phydev, 1, MT7620_PHY_PAGE,
					  tuning[i].page);
		if (ret)
			break;
		ret = __phy_package_write(phydev, 1, tuning[i].reg,
					  shared->bga ? tuning[i].bga :
					  tuning[i].qfn);
		if (ret)
			break;
	}

	restore = __phy_package_write(phydev, 1, MT7620_PHY_PAGE, oldpage);
	if (!ret)
		ret = restore;
unlock:
	phy_unlock_mdio_bus(phydev);
	return ret;
}

static int mt7620_ephy_config_init(struct phy_device *phydev)
{
	static const u16 local[] = { 0x1111, 0x1010, 0x1515, 0x0f0f, 0x1313 };
	struct mt7620_ephy_shared *shared = phy_package_get_priv(phydev);
	int ret = 0;

	/* Retry failed initialization; do not retune the other active PHYs
	 * when one port is reattached or resumes from power down.
	 */
	phy_package_lock(phydev);
	if (!shared->initialized) {
		ret = mt7620_ephy_init_shared(phydev);
		if (!ret)
			shared->initialized = true;
	}
	phy_package_unlock(phydev);
	if (ret)
		return ret;

	ret = phy_write_paged(phydev, 0x8000, 30, 0xa000);
	if (ret)
		return ret;

	return phy_write_paged(phydev, 0xa000, 16, local[phydev->mdio.addr]);
}

static int mt7620_ephy_probe(struct phy_device *phydev)
{
	struct device_node *np = dev_of_node(&phydev->mdio.bus->dev);
	struct mt7620_ephy_shared *shared;
	struct regmap *sysc;
	u32 rev;
	int ret;

	/* The integrated MDIO bus uses the hardware's base address zero. */
	if (phydev->mdio.addr >= MT7620_PHY_COUNT)
		return -EINVAL;

	sysc = syscon_regmap_lookup_by_phandle(np, "mediatek,sysc");
	if (IS_ERR(sysc))
		return dev_err_probe(&phydev->mdio.dev, PTR_ERR(sysc),
				     "failed to get system controller\n");

	ret = regmap_read(sysc, MT7620_SYSC_REV, &rev);
	if (ret)
		return ret;

	ret = devm_phy_package_join(&phydev->mdio.dev, phydev, 0,
				    sizeof(*shared));
	if (ret)
		return ret;

	shared = phy_package_get_priv(phydev);
	phy_package_lock(phydev);
	shared->bga = !!(rev & MT7620_SYSC_REV_BGA);
	phy_package_unlock(phydev);

	return 0;
}

static struct phy_driver mt7620_ephy_drivers[] = {
	{
		PHY_ID_MATCH_MODEL(MT7620_PHY_ID),
		.name		= "MediaTek MT7620 PHY",
		.flags		= PHY_IS_INTERNAL,
		.probe		= mt7620_ephy_probe,
		.config_init	= mt7620_ephy_config_init,
		.read_page	= mt7620_ephy_read_page,
		.write_page	= mt7620_ephy_write_page,
		.suspend	= genphy_suspend,
		.resume		= genphy_resume,
	},
};
module_phy_driver(mt7620_ephy_drivers);

static const struct mdio_device_id mt7620_ephy_tbl[] = {
	{ PHY_ID_MATCH_MODEL(MT7620_PHY_ID) },
	{ }
};
MODULE_DEVICE_TABLE(mdio, mt7620_ephy_tbl);

MODULE_DESCRIPTION("MediaTek MT7620 Fast Ethernet PHY driver");
MODULE_LICENSE("GPL");
